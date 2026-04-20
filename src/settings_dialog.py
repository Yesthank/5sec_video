"""저장 경로 / 파일명 템플릿 / 기본 FPS 설정 다이얼로그."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config import ALLOWED_FPS, AppConfig, preview_filename, save_config


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("5sec_video — 설정")
        self.setModal(True)
        self._config = config

        self._build_ui()
        self._refresh_preview()

    def _build_ui(self) -> None:
        # 저장 폴더
        self._dir_edit = QLineEdit(self._config.save_dir)
        browse_btn = QPushButton("찾아보기...")
        browse_btn.clicked.connect(self._on_browse)

        dir_row = QHBoxLayout()
        dir_row.addWidget(self._dir_edit, 1)
        dir_row.addWidget(browse_btn)
        dir_widget = QWidget()
        dir_widget.setLayout(dir_row)

        # 파일명 템플릿
        self._template_edit = QLineEdit(self._config.filename_template)
        self._template_edit.textChanged.connect(self._refresh_preview)

        self._preview_label = QLabel()
        self._preview_label.setStyleSheet("color: #888;")

        help_label = QLabel(
            "토큰: %Y %m %d %H %M %S, %counter% (4자리 자동 증가)"
        )
        help_label.setStyleSheet("color: #888; font-size: 11px;")

        # 기본 FPS
        self._fps_combo = QComboBox()
        for fps in ALLOWED_FPS:
            self._fps_combo.addItem(f"{fps} fps", fps)
        self._fps_combo.setCurrentIndex(ALLOWED_FPS.index(self._config.fps))

        # 오디오 녹음 (기본 마이크)
        self._audio_check = QCheckBox("마이크 오디오 함께 녹음")
        self._audio_check.setChecked(self._config.audio_enabled)
        audio_hint = QLabel(
            "※ 시스템의 기본 입력 장치(마이크)를 사용합니다. "
            "장치가 없거나 캡처에 실패하면 영상만 저장됩니다."
        )
        audio_hint.setStyleSheet("color: #888; font-size: 11px;")
        audio_hint.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("저장 폴더:", dir_widget)
        form.addRow("파일명 템플릿:", self._template_edit)
        form.addRow("", help_label)
        form.addRow("미리보기:", self._preview_label)
        form.addRow("기본 FPS:", self._fps_combo)
        form.addRow("오디오:", self._audio_check)
        form.addRow("", audio_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(460, self.sizeHint().height())

    # ── 슬롯 ──────────────────────────────────────────────────────────────
    def _on_browse(self) -> None:
        start = self._dir_edit.text() or str(Path.cwd())
        chosen = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", start)
        if chosen:
            self._dir_edit.setText(chosen)

    def _refresh_preview(self) -> None:
        try:
            self._preview_label.setText(preview_filename(self._template_edit.text()))
        except Exception as exc:  # noqa: BLE001
            self._preview_label.setText(f"(템플릿 오류: {exc})")

    def _on_accept(self) -> None:
        self._config.save_dir = self._dir_edit.text().strip() or "./recordings"
        self._config.filename_template = (
            self._template_edit.text().strip() or "clip_%Y%m%d_%H%M%S"
        )
        self._config.fps = int(self._fps_combo.currentData())
        self._config.audio_enabled = self._audio_check.isChecked()
        self._config.validated()
        save_config(self._config)
        self.accept()

    # ── 외부 API ──────────────────────────────────────────────────────────
    def updated_config(self) -> AppConfig:
        return self._config


def _cli_test() -> None:
    """설정 다이얼로그 단독 테스트.

    사용 예:
        python -m src.settings_dialog
    """
    import sys

    from PySide6.QtWidgets import QApplication

    from src.config import load_config

    app = QApplication(sys.argv)
    cfg = load_config()
    dlg = SettingsDialog(cfg)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        print(f"saved: {dlg.updated_config()}")
    else:
        print("cancelled")
    sys.exit(0)


if __name__ == "__main__":
    _cli_test()
