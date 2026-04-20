"""비디오(mp4) + 오디오(wav) → 최종 mp4 muxing.

- imageio-ffmpeg가 번들한 ffmpeg 실행 파일을 사용 (시스템 ffmpeg 설치 불필요)
- 비디오는 그대로 복사(-c:v copy), 오디오는 AAC로 재인코딩
- 길이는 짧은 쪽에 맞춤(-shortest)
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def mux_video_audio(video_path: Path, audio_path: Path, output_path: Path) -> Path:
    """video + audio를 하나의 mp4로 병합.

    기존 output_path가 있으면 덮어씀. 실패 시 RuntimeError를 발생시킴.
    """
    video_path = Path(video_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]

    # 콘솔 창이 뜨지 않도록 Windows에서는 CREATE_NO_WINDOW 사용
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffmpeg 실행 실패: {exc}") from exc

    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"ffmpeg mux 실패 (rc={result.returncode}):\n{result.stderr.strip()}"
        )

    return output_path
