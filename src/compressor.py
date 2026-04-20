"""mp4 파일을 빠르게 H.264로 재인코딩해 용량을 줄임.

- 캡처 시 mp4v 코덱은 압축률이 낮아 파일이 금방 커짐 (수~수십 MB/초)
- libx264 + preset=veryfast + crf 23 정도면 체감 화질 손실 없이 5~10배 작아짐
- 오디오 스트림은 재인코딩 없이 복사 (-c:a copy)
- ffmpeg은 imageio-ffmpeg 번들 사용 (시스템 설치 불필요)
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _creation_flags() -> int:
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return flags


def compress_mp4(
    input_path: Path,
    *,
    preset: str = "veryfast",
    crf: int = 23,
    replace: bool = True,
    suffix: str = "_compressed",
) -> Path:
    """입력 mp4를 H.264로 재인코딩해 저장.

    replace=True면 원본 파일을 결과물로 교체, False면 같은 폴더에 `<name><suffix>.mp4` 생성.
    실패 시 RuntimeError를 발생시키며, 부분적으로 생성된 출력 파일은 삭제한다.
    """
    input_path = Path(input_path)
    if not input_path.exists() or input_path.stat().st_size == 0:
        raise RuntimeError(f"입력 파일이 없거나 비어있음: {input_path}")

    tmp_out = input_path.with_suffix(".compress.tmp.mp4")

    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(tmp_out),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=_creation_flags(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffmpeg 실행 실패: {exc}") from exc

    if result.returncode != 0 or not tmp_out.exists() or tmp_out.stat().st_size == 0:
        try:
            tmp_out.unlink()
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            f"ffmpeg 압축 실패 (rc={result.returncode}):\n{result.stderr.strip()}"
        )

    if replace:
        final = input_path
    else:
        final = input_path.with_name(f"{input_path.stem}{suffix}{input_path.suffix}")

    # 크로스드라이브 호환: 기존 파일 삭제 후 이동
    try:
        if final.exists():
            final.unlink()
    except Exception as exc:  # noqa: BLE001
        try:
            tmp_out.unlink()
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"기존 출력 파일을 삭제할 수 없음: {final} ({exc})") from exc

    tmp_out.replace(final)
    return final


def compress_mp4_async(
    input_path: Path,
    *,
    preset: str = "veryfast",
    crf: int = 23,
    replace: bool = True,
    on_success: Callable[[Path, int, int], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> threading.Thread:
    """compress_mp4를 백그라운드 스레드로 실행.

    on_success(out_path, original_size, compressed_size)
    on_error(exception)
    """
    input_path = Path(input_path)
    original_size = input_path.stat().st_size if input_path.exists() else 0

    def _run():
        try:
            out = compress_mp4(input_path, preset=preset, crf=crf, replace=replace)
        except BaseException as exc:  # noqa: BLE001
            if on_error is not None:
                on_error(exc)
            return
        if on_success is not None:
            on_success(out, original_size, out.stat().st_size if out.exists() else 0)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
