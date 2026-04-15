"""화면 영역 캡처 → mp4 인코딩.

Step 2 최소 기능:
- 고정된 (x, y, w, h) 영역과 fps, 출력 경로를 받아 별도 스레드에서 녹화
- start() / stop()으로 제어
- mss로 화면 캡처, cv2.VideoWriter(mp4v)로 인코딩
- 마우스 커서는 포함하지 않음 (mss 기본 동작)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np


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
    """주어진 영역을 지정된 fps로 mp4 파일에 기록."""

    def __init__(self, region: Region, fps: int, output_path: Path) -> None:
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
        self.output_path = Path(output_path)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_count = 0
        self._writer: cv2.VideoWriter | None = None
        self._error: BaseException | None = None

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("recorder already started")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # VideoWriter는 메인 스레드에서 열어 실패를 즉시 전파
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(
            str(self.output_path),
            fourcc,
            float(self.fps),
            (self.region.width, self.region.height),
        )
        if not self._writer.isOpened():
            self._writer = None
            raise RuntimeError(
                f"cv2.VideoWriter failed to open: {self.output_path}\n"
                f"(size={self.region.width}x{self.region.height}, fps={self.fps})"
            )

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

        if self._error is not None:
            err = self._error
            self._error = None
            raise RuntimeError(f"recording failed: {err}") from err

        if self._frame_count == 0:
            raise RuntimeError("no frames captured")
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


def _cli_test() -> None:
    """간단한 동작 확인용 CLI.

    사용 예:
        python -m src.recorder --x 100 --y 100 --w 640 --h 360 --fps 30 --seconds 3
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
        "--out",
        type=Path,
        default=Path("recordings") / f"test_{datetime.now():%Y%m%d_%H%M%S}.mp4",
    )
    args = parser.parse_args()

    region = Region(args.x, args.y, args.w, args.h)
    recorder = ScreenRecorder(region=region, fps=args.fps, output_path=args.out)

    print(f"recording {args.seconds}s @ {args.fps}fps → {args.out}")
    recorder.start()
    try:
        time.sleep(args.seconds)
    finally:
        out = recorder.stop()
    print(f"done. frames={recorder.frame_count}, file={out}")


if __name__ == "__main__":
    _cli_test()
