"""녹화 컨트롤 바.

Step 4:
- 작은 프레임리스 / 항상 위 / 드래그 가능한 컨트롤 바
- [● Rec] / [■ Stop] 토글 버튼
- 경과 시간 표시 (mm:ss)
- FPS 선택 (10 / 30 / 60)
- 닫기 버튼

이 위젯은 UI만 담당하고, 실제 녹화는 외부에서 시그널을 받아 처리합니다:
- start_requested(fps: int)
- stop_requested()
- close_requested()

외부에서 set_recording(True/False)을 호출해 버튼/타이머 상태를 동기화합니다.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

ALLOWED_FPS = (10, 30, 60)


class ControllerBar(QWidget):
    start_requested = Signal(int)  # fps
    stop_requested = Signal()
    close_requested = Signal()

    def __init__(self, default_fps: int = 30) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        if default_fps not in ALLOWED_FPS:
            default_fps = 30

        self._is_recording = False
        self._elapsed_sec = 0
        self._drag_offset: QPoint | None = None

        self._build_ui(default_fps)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self, default_fps: int) -> None:
        self.setStyleSheet(
            """
            QWidget { background: #1e1e1e; color: #eaeaea; font-size: 12px; }
            QPushButton {
                background: #2d2d2d; border: 1px solid #444; border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background: #3a3a3a; }
            QPushButton#record { background: #b03030; border-color: #d04040; }
            QPushButton#record:hover { background: #c83838; }
            QComboBox {
                background: #2d2d2d; border: 1px solid #444; border-radius: 4px;
                padding: 2px 6px;
            }
            QLabel#elapsed { font-family: Consolas, monospace; min-width: 44px; }
            """
        )

        self._record_btn = QPushButton("● Rec")
        self._record_btn.setObjectName("record")
        self._record_btn.clicked.connect(self._on_record_clicked)

        self._elapsed_label = QLabel("00:00")
        self._elapsed_label.setObjectName("elapsed")
        self._elapsed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._fps_combo = QComboBox()
        for fps in ALLOWED_FPS:
            self._fps_combo.addItem(f"{fps} fps", fps)
        self._fps_combo.setCurrentIndex(ALLOWED_FPS.index(default_fps))

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedWidth(28)
        self._close_btn.clicked.connect(self._on_close_clicked)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        layout.addWidget(self._record_btn)
        layout.addWidget(self._elapsed_label)
        layout.addWidget(self._fps_combo)
        layout.addWidget(self._close_btn)

        self.adjustSize()

    # ── 외부 API ──────────────────────────────────────────────────────────
    def set_recording(self, recording: bool) -> None:
        """녹화 상태를 외부에서 동기화."""
        self._is_recording = recording
        if recording:
            self._elapsed_sec = 0
            self._update_elapsed_label()
            self._tick_timer.start()
            self._record_btn.setText("■ Stop")
            self._fps_combo.setEnabled(False)
        else:
            self._tick_timer.stop()
            self._record_btn.setText("● Rec")
            self._fps_combo.setEnabled(True)

    def selected_fps(self) -> int:
        return int(self._fps_combo.currentData())

    def place_near(self, region_top_left_logical: QPoint) -> None:
        """선택 영역의 좌상단(논리 좌표) 근처에 컨트롤 바를 배치."""
        self.adjustSize()
        target = QPoint(region_top_left_logical.x(), region_top_left_logical.y() - self.height() - 6)
        if target.y() < 0:
            target = QPoint(region_top_left_logical.x(), region_top_left_logical.y() + 6)
        self.move(target)

    # ── 슬롯 ──────────────────────────────────────────────────────────────
    def _on_record_clicked(self) -> None:
        if self._is_recording:
            self.stop_requested.emit()
        else:
            self.start_requested.emit(self.selected_fps())

    def _on_close_clicked(self) -> None:
        if self._is_recording:
            # 녹화 중에는 먼저 정지 요청
            self.stop_requested.emit()
        self.close_requested.emit()
        self.close()

    def _on_tick(self) -> None:
        self._elapsed_sec += 1
        self._update_elapsed_label()

    def _update_elapsed_label(self) -> None:
        m, s = divmod(self._elapsed_sec, 60)
        self._elapsed_label.setText(f"{m:02d}:{s:02d}")

    # ── 드래그로 이동 ─────────────────────────────────────────────────────
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None


def _cli_test() -> None:
    """컨트롤 바 단독 테스트.

    오버레이로 영역을 잡은 뒤 컨트롤 바를 띄우고, 실제로 녹화/중지가 동작합니다.

    사용 예:
        python -m src.controller
    """
    import sys
    from datetime import datetime
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from src.overlay import RegionSelector
    from src.recorder import Region, ScreenRecorder

    app = QApplication(sys.argv)

    state: dict = {"recorder": None, "bar": None, "region": None}

    def start_recording(fps: int) -> None:
        out = Path("recordings") / f"clip_{datetime.now():%Y%m%d_%H%M%S}.mp4"
        recorder = ScreenRecorder(region=state["region"], fps=fps, output_path=out)
        recorder.start()
        state["recorder"] = recorder
        state["bar"].set_recording(True)
        print(f"recording → {out}")

    def stop_recording() -> None:
        recorder: ScreenRecorder | None = state["recorder"]
        if recorder is None:
            return
        out = recorder.stop()
        state["recorder"] = None
        state["bar"].set_recording(False)
        print(f"saved: {out} (frames={recorder.frame_count})")

    def on_close() -> None:
        if state["recorder"] is not None:
            state["recorder"].stop()
        app.quit()

    def on_selected(region: Region) -> None:
        state["region"] = region
        bar = ControllerBar()
        bar.start_requested.connect(start_recording)
        bar.stop_requested.connect(stop_recording)
        bar.close_requested.connect(on_close)

        # 논리 좌표로 환산해서 컨트롤 바 위치 지정
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio()
        bar.place_near(QPoint(int(region.x / ratio), int(region.y / ratio)))
        bar.show()
        bar.raise_()
        state["bar"] = bar

    selector = RegionSelector()
    selector.selected.connect(on_selected)
    selector.cancelled.connect(app.quit)
    selector.show()
    selector.raise_()
    selector.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    _cli_test()
