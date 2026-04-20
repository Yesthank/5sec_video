"""config.json 로드/저장 및 파일명 템플릿 처리.

지원 토큰 (ComfyUI VideoCombine 스타일):
    %Y %m %d %H %M %S   - 현재 시각 (zero-padded)
    %counter%           - 기존 파일과 충돌하지 않는 4자리 증가 번호 (0001, 0002, ...)

파일명에 확장자(.mp4)는 붙이지 않으며, resolve_output_path()가 자동으로 추가합니다.
%counter%가 없는데 파일이 이미 존재하면 `_1`, `_2` ... 접미사를 붙여 고유한 경로를 만듭니다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
ALLOWED_FPS = (10, 30, 60)


def resolve_save_dir(save_dir: str | Path) -> Path:
    """상대 경로는 프로젝트 루트 기준으로 절대화."""
    p = Path(save_dir)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


AUDIO_SOURCES = ("system", "microphone")


@dataclass
class AppConfig:
    save_dir: str = "./recordings"
    filename_template: str = "clip_%Y%m%d_%H%M%S"
    fps: int = 30
    audio_enabled: bool = True
    audio_source: str = "system"  # "system" = 스피커 루프백, "microphone" = 마이크
    audio_device: str = ""  # microphone 모드에서만 사용. "" = 시스템 기본 입력
    auto_compress: bool = False  # 녹화 후 libx264로 자동 재인코딩 (용량 축소)

    def validated(self) -> "AppConfig":
        if self.fps not in ALLOWED_FPS:
            self.fps = 30
        if not self.filename_template.strip():
            self.filename_template = "clip_%Y%m%d_%H%M%S"
        if not self.save_dir.strip():
            self.save_dir = "./recordings"
        self.audio_enabled = bool(self.audio_enabled)
        if self.audio_source not in AUDIO_SOURCES:
            self.audio_source = "system"
        self.audio_device = str(self.audio_device or "")
        self.auto_compress = bool(self.auto_compress)
        return self


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    if not path.exists():
        cfg = AppConfig()
        save_config(cfg, path)
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AppConfig()
    cfg = AppConfig(
        save_dir=str(data.get("save_dir", AppConfig.save_dir)),
        filename_template=str(data.get("filename_template", AppConfig.filename_template)),
        fps=int(data.get("fps", AppConfig.fps)),
        audio_enabled=bool(data.get("audio_enabled", AppConfig.audio_enabled)),
        audio_source=str(data.get("audio_source", AppConfig.audio_source)),
        audio_device=str(data.get("audio_device", AppConfig.audio_device)),
        auto_compress=bool(data.get("auto_compress", AppConfig.auto_compress)),
    )
    return cfg.validated()


def save_config(cfg: AppConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg.validated()), indent=2), encoding="utf-8")


# ── 파일명 템플릿 ─────────────────────────────────────────────────────────
_COUNTER_SENTINEL = "\x00COUNTER\x00"


def _apply_time_tokens(template: str, now: datetime) -> str:
    # %counter%의 %c가 strftime의 'locale 날짜시간' 토큰과 충돌하므로 임시 치환
    safe = template.replace("%counter%", _COUNTER_SENTINEL)
    rendered = now.strftime(safe)
    return rendered.replace(_COUNTER_SENTINEL, "%counter%")


def resolve_output_path(
    save_dir: str | Path,
    template: str,
    *,
    now: datetime | None = None,
    extension: str = ".mp4",
) -> Path:
    """템플릿을 실제 파일 경로로 해석.

    - %counter% 가 있으면 4자리 zero-padded 번호로 채우고, 파일이 존재하지 않는 가장 작은 번호 사용
    - %counter% 가 없고 파일이 이미 존재하면 `_1`, `_2` ... 접미사를 붙여 고유 경로 생성
    """
    now = now or datetime.now()
    save_dir = resolve_save_dir(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    base = _apply_time_tokens(template, now)

    if "%counter%" in base:
        for n in range(1, 100_000):
            candidate = save_dir / (base.replace("%counter%", f"{n:04d}") + extension)
            if not candidate.exists():
                return candidate
        raise RuntimeError("counter overflow (100000+)")

    candidate = save_dir / (base + extension)
    if not candidate.exists():
        return candidate
    for n in range(1, 100_000):
        alt = save_dir / f"{base}_{n}{extension}"
        if not alt.exists():
            return alt
    raise RuntimeError("filename collision overflow")


def preview_filename(template: str, *, extension: str = ".mp4") -> str:
    now = datetime.now()
    base = _apply_time_tokens(template, now)
    base = base.replace("%counter%", "0001")
    return base + extension
