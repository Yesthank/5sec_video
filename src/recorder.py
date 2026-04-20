"""화면 영역 캡처 → mp4 인코딩 (+ 선택적 오디오 muxing).

- 고정된 (x, y, w, h) 영역과 fps, 출력 경로를 받아 별도 스레드에서 녹화
- start() / stop()으로 제어
- mss로 화면 캡처, cv2.VideoWriter(mp4v)로 영상 인코딩
- 마우스 커서는 포함하지 않음 (mss 기본 동작)
- audio_enabled=True면 sounddevice로 마이크 캡처 → 정지 시 ffmpeg으로 muxing
  오디오 장치가 없거나 실패하면 영상만 저장 (graceful fallback)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np

from src.audio_recorder import MicAudioRecorder, SystemAudioRecorder
from src.muxer import mux_video_audio


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int

    def to_mss(self) -> dict:
        return {
            "left": self.x,
            "top": self.y,
            "width": self.width,
            "height": self.height,
        }


class ScreenRecorder:
    """주어진 영역을 지정된 fps로 mp4 파일에 기록 (+ 선택적 오디오)."""

    def __init__(
        self,
        region: Region,
        fps: int,
        output_path: Path,
        *,
        audio_enabled: bool = False,
        audio_source: str = "system",  # "system" | "microphone"
        audio_device: int | str | None = None,  # microphone 모드에서만 사용
    ) -> None:
        if fps not in (10, 30, 60):
            raise ValueError(f"fps must be 10, 30, or 60 (got {fps})")
        if region.width <= 0 or region.height <= 0:
            raise ValueError("region width/height must be positive")

        # mp4 인코더는 짝수 픽셀을 선호 — 홀수면 1픽셀 잘라냄
        self.region = Region(
            x=region.x,
            y=region.y,
            width=region.width - (region.width % 2),
            height=region.height - (region.height % 2),
        )
        self.fps = fps
        self.audio_enabled = bool(audio_enabled)
        self.audio_source = audio_source if audio_source in ("system", "microphone") else "system"
        self.audio_device = audio_device

        # 최종 사용자 경로와, 내부적으로 쓰는 영상 전용 경로를 분리
        self.output_path = Path(output_path)
        if self.audio_enabled:
            self._video_path = self.output_path.with_suffix(".video.tmp.mp4")
            self._audio_path = self.output_path.with_suffix(".audio.tmp.wav")
        else:
            self._video_path = self.output_path
            self._audio_path = None

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_count = 0
        self._writer: cv2.VideoWriter | None = None
        self._error: BaseException | None = None
        self._audio: SystemAudioRecorder | MicAudioRecorder | None = None
        # 오디오 시작에 실패했지만 녹화는 계속 — UI에서 참고용으로 읽을 수 있음
        self.audio_error: str | None = None
        self.mux_error: str | None = None
        # 오디오 레벨 / 선택된 장치 정보 (stop 이후 읽기용)
        self.audio_device_name: str = ""
        self.audio_peak_dbfs: float = -120.0
        self.audio_silent: bool = False

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("recorder already started")
        self._video_path.parent.mkdir(parents=True, exist_ok=True)

        # VideoWriter는 메인 스레드에서 열어 실패를 즉시 전파
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(
            str(self._video_path),
            fourcc,
            float(self.fps),
            (self.region.width, self.region.height),
        )
        if not self._writer.isOpened():
            self._writer = None
            raise RuntimeError(
                f"cv2.VideoWriter failed to open: {self._video_path}\n"
                f"(size={self.region.width}x{self.region.height}, fps={self.fps})"
            )

        # 오디오 시작은 best-effort — 실패해도 영상만 저장
        self.audio_error = None
        self.mux_error = None
        self.audio_device_name = ""
        self.audio_peak_dbfs = -120.0
        self.audio_silent = False
        if self.audio_enabled and self._audio_path is not None:
            try:
                if self.audio_source == "system":
                    self._audio = SystemAudioRecorder(output_path=self._audio_path)
                else:
                    self._audio = MicAudioRecorder(
                        output_path=self._audio_path,
                        device=self.audio_device,
                    )
                self._audio.start()
                self.audio_device_name = self._audio.device_name
            except Exception as exc:  # noqa: BLE001
                self._audio = None
                self.audio_error = str(exc)
                print(f"[5sec_video] audio start failed: {exc} — continuing video-only")

        self._stop_event.clear()
        self._frame_count = 0
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> Path:
        if self._thread is None:
            raise RuntimeError("recorder not started")
        self._stop_event.set()
        self._thread.join()
        self._thread = None

        # 오디오 중지 (녹화 중이었다면) — 어떤 결과든 레벨/무음 여부는 기록
        audio_out: Path | None = None
        if self._audio is not None:
            audio = self._audio
            self._audio = None
            try:
                audio_out = audio.stop()
            except Exception as exc:  # noqa: BLE001
                audio_out = None
                self.audio_error = str(exc)
                print(f"[5sec_video] audio stop failed: {exc}")
            finally:
                self.audio_peak_dbfs = audio.peak_dbfs
                self.audio_silent = audio.is_silent_output()

        # 여기서부터는 실패해도 반드시 임시 파일을 정리해야 하므로 try/finally로 감쌈
        try:
            if self._error is not None:
                err = self._error
                self._error = None
                raise RuntimeError(f"recording failed: {err}") from err

            if self._frame_count == 0:
                raise RuntimeError("no frames captured")
            if not self._video_path.exists() or self._video_path.stat().st_size == 0:
                raise RuntimeError(f"output file missing or empty: {self._video_path}")

            if self.audio_enabled and audio_out is not None and audio_out.exists() and audio_out.stat().st_size > 0:
                try:
                    mux_video_audio(self._video_path, audio_out, self.output_path)
                except Exception as exc:  # noqa: BLE001
                    # mux 실패 시 영상만이라도 건지기
                    self.mux_error = str(exc)
                    print(f"[5sec_video] mux failed: {exc} — saving video-only")
                    _move_over(self._video_path, self.output_path)
            elif self.audio_enabled:
                # 오디오를 못 얻었으면 영상 파일을 최종 경로로 이동
                _move_over(self._video_path, self.output_path)

            if not self.output_path.exists() or self.output_path.stat().st_size == 0:
                raise RuntimeError(f"output file missing or empty: {self.output_path}")

            return self.output_path
        finally:
            # 최종 출력과 경로가 다른 임시 파일만 제거
            if self._video_path != self.output_path:
                _safe_unlink(self._video_path)
            if audio_out is not None:
                _safe_unlink(audio_out)

    def _run(self) -> None:
        assert self._writer is not None
        writer = self._writer
        frame_interval = 1.0 / self.fps
        bbox = self.region.to_mss()

        try:
            with mss.mss() as sct:
                next_frame_at = time.perf_counter()
                while not self._stop_event.is_set():
                    shot = sct.grab(bbox)
                    # mss는 BGRA → cv2는 BGR
                    frame = np.asarray(shot, dtype=np.uint8)[:, :, :3]
                    writer.write(frame)
                    self._frame_count += 1

                    next_frame_at += frame_interval
                    sleep_for = next_frame_at - time.perf_counter()
                    if sleep_for > 0:
                        # 정지 신호에 빠르게 반응하기 위해 wait 사용
                        if self._stop_event.wait(sleep_for):
                            break
                    else:
                        # 캡처가 밀린 경우 다음 기준 시각을 현재로 리셋
                        next_frame_at = time.perf_counter()
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
        finally:
            writer.release()
            self._writer = None


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except Exception:  # noqa: BLE001
        pass


def _move_over(src: Path, dst: Path) -> None:
    """src 파일을 dst 경로로 이동 (dst가 있으면 교체)."""
    if src == dst:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            dst.unlink()
        except Exception:  # noqa: BLE001
            pass
    src.replace(dst)


def _cli_test() -> None:
    """간단한 동작 확인용 CLI.

    사용 예:
        python -m src.recorder --x 100 --y 100 --w 640 --h 360 --fps 30 --seconds 3
        python -m src.recorder --audio system       # 시스템 오디오(스피커) 루프백
        python -m src.recorder --audio microphone   # 마이크
    """
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser(description="ScreenRecorder smoke test")
    parser.add_argument("--x", type=int, default=100)
    parser.add_argument("--y", type=int, default=100)
    parser.add_argument("--w", type=int, default=640)
    parser.add_argument("--h", type=int, default=360)
    parser.add_argument("--fps", type=int, default=30, choices=[10, 30, 60])
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument(
        "--audio",
        choices=["off", "system", "microphone"],
        default="off",
        help="오디오 소스 (off=영상만, system=스피커 루프백, microphone=마이크)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("recordings") / f"test_{datetime.now():%Y%m%d_%H%M%S}.mp4",
    )
    args = parser.parse_args()

    region = Region(args.x, args.y, args.w, args.h)
    recorder = ScreenRecorder(
        region=region,
        fps=args.fps,
        output_path=args.out,
        audio_enabled=(args.audio != "off"),
        audio_source=args.audio if args.audio != "off" else "system",
    )

    print(f"recording {args.seconds}s @ {args.fps}fps (audio={args.audio}) → {args.out}")
    recorder.start()
    try:
        time.sleep(args.seconds)
    finally:
        out = recorder.stop()
    print(f"done. frames={recorder.frame_count}, file={out}")
    if recorder.audio_enabled:
        print(f"audio device: {recorder.audio_device_name!r}")
        print(f"audio peak: {recorder.audio_peak_dbfs:.1f} dBFS  silent={recorder.audio_silent}")
    if recorder.audio_error:
        print(f"audio error: {recorder.audio_error}")
    if recorder.mux_error:
        print(f"mux error: {recorder.mux_error}")


if __name__ == "__main__":
    _cli_test()
