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

from src.audio_recorder import AudioRecorder
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
        audio_device: int | str | None = None,
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
        self._audio: AudioRecorder | None = None
        # 오디오 시작에 실패했지만 녹화는 계속 — UI에서 참고용으로 읽을 수 있음
        self.audio_error: str | None = None
        self.mux_error: str | None = None

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
        if self.audio_enabled and self._audio_path is not None:
            try:
                self._audio = AudioRecorder(
                    output_path=self._audio_path,
                    device=self.audio_device,
                )
                self._audio.start()
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

        # 오디오 중지 (녹화 중이었다면)
        audio_out: Path | None = None
        if self._audio is not None:
            try:
                audio_out = self._audio.stop()
            except Exception as exc:  # noqa: BLE001
                audio_out = None
                self.audio_error = str(exc)
                print(f"[5sec_video] audio stop failed: {exc}")
            finally:
                self._audio = None

        if self._error is not None:
            err = self._error
            self._error = None
            raise RuntimeError(f"recording failed: {err}") from err

        if self._frame_count == 0:
            raise RuntimeError("no frames captured")
        if not self._video_path.exists() or self._video_path.stat().st_size == 0:
            raise RuntimeError(f"output file missing or empty: {self._video_path}")

        # 오디오가 있으면 muxing, 아니면 영상 파일을 그대로 최종 경로로 사용
        if self.audio_enabled and audio_out is not None and audio_out.exists() and audio_out.stat().st_size > 0:
            try:
                mux_video_audio(self._video_path, audio_out, self.output_path)
            except Exception as exc:  # noqa: BLE001
                # mux 실패 시 영상만이라도 건지기
                self.mux_error = str(exc)
                print(f"[5sec_video] mux failed: {exc} — saving video-only")
                try:
                    if self.output_path.exists():
                        self.output_path.unlink()
                    self._video_path.replace(self.output_path)
                except Exception:  # noqa: BLE001
                    pass
            else:
                # 성공 — 임시 파일 정리
                _safe_unlink(self._video_path)
            _safe_unlink(audio_out)
        elif self.audio_enabled:
            # 오디오를 못 얻었으면 영상 파일을 최종 경로로 이동
            try:
                if self.output_path.exists():
                    self.output_path.unlink()
                self._video_path.replace(self.output_path)
            except Exception as exc:  # noqa: BLE001
                print(f"[5sec_video] failed to move video file: {exc}")

        if not self.output_path.exists() or self.output_path.stat().st_size == 0:
            raise RuntimeError(f"output file missing or empty: {self.output_path}")

        return self.output_path

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


def _cli_test() -> None:
    """간단한 동작 확인용 CLI.

    사용 예:
        python -m src.recorder --x 100 --y 100 --w 640 --h 360 --fps 30 --seconds 3
        python -m src.recorder --audio   # 마이크도 함께 녹음
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
    parser.add_argument("--audio", action="store_true", help="마이크 오디오 함께 녹음")
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
        audio_enabled=args.audio,
    )

    print(f"recording {args.seconds}s @ {args.fps}fps (audio={args.audio}) → {args.out}")
    recorder.start()
    try:
        time.sleep(args.seconds)
    finally:
        out = recorder.stop()
    print(f"done. frames={recorder.frame_count}, file={out}")
    if recorder.audio_error:
        print(f"audio: {recorder.audio_error}")
    if recorder.mux_error:
        print(f"mux: {recorder.mux_error}")


if __name__ == "__main__":
    _cli_test()
