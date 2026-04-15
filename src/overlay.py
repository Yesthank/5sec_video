"""풀스크린 영역 선택 오버레이.

Step 3:
- 가상 데스크톱(모든 모니터) 전체를 덮는 반투명 오버레이 표시
- 마우스 드래그로 사각형 영역 지정
- 마우스 버튼을 떼면 `selected(Region)` 시그널 발생
- ESC 키 또는 우클릭으로 취소 → `cancelled()` 시그널 발생

좌표는 mss/recorder가 요구하는 **물리 픽셀** 좌표로 변환되어 전달됩니다.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.recorder import Region


class RegionSelector(QWidget):
    """풀스크린 오버레이 위에서 드래그로 영역을 선택하는 위젯."""

    selected = Signal(Region)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # 모든 모니터를 덮도록 가상 데스크톱 전체 영역 사용
        virtual_geo = QRect()
        for screen in QGuiApplication.screens():
            virtual_geo = virtual_geo.united(screen.geometry())
        self.setGeometry(virtual_geo)
        self._virtual_origin = virtual_geo.topLeft()

        self._origin: QPoint | None = None
        self._current: QPoint | None = None

    # ── 이벤트 ────────────────────────────────────────────────────────────
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        rect = QRect(self._origin, event.position().toPoint()).normalized()
        self._origin = None
        self._current = None

        # 너무 작은 영역은 무시 (실수 클릭 방지)
        if rect.width() < 8 or rect.height() < 8:
            self._cancel()
            return

        region = self._to_physical_region(rect)
        self.close()
        self.selected.emit(region)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    # ── 그리기 ────────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # 전체를 어둡게
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        if self._origin is not None and self._current is not None:
            rect = QRect(self._origin, self._current).normalized()

            # 선택 영역은 투명하게 비움
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # 테두리
            pen = QPen(QColor(0, 200, 255), 2)
            painter.setPen(pen)
            painter.drawRect(rect)

            # 크기 라벨
            label = f"{rect.width()} x {rect.height()}"
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect.x() + 6, max(rect.y() - 6, 14), label)

    # ── 내부 ──────────────────────────────────────────────────────────────
    def _cancel(self) -> None:
        self._origin = None
        self._current = None
        self.close()
        self.cancelled.emit()

    def _to_physical_region(self, logical_rect: QRect) -> Region:
        """위젯 로컬 좌표 → 화면 물리 픽셀 좌표로 변환."""
        # 위젯 로컬 → 가상 데스크톱(논리) 좌표
        global_top_left = logical_rect.topLeft() + self._virtual_origin

        # 클릭이 발생한 화면의 devicePixelRatio 사용
        screen = QGuiApplication.screenAt(global_top_left) or QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio()

        return Region(
            x=int(round(global_top_left.x() * ratio)),
            y=int(round(global_top_left.y() * ratio)),
            width=int(round(logical_rect.width() * ratio)),
            height=int(round(logical_rect.height() * ratio)),
        )


def _cli_test() -> None:
    """오버레이 단독 테스트.

    사용 예:
        python -m src.overlay
    """
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    selector = RegionSelector()

    def on_selected(region: Region) -> None:
        print(f"selected: x={region.x}, y={region.y}, w={region.width}, h={region.height}")
        app.quit()

    def on_cancelled() -> None:
        print("cancelled")
        app.quit()

    selector.selected.connect(on_selected)
    selector.cancelled.connect(on_cancelled)
    selector.show()
    selector.raise_()
    selector.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    _cli_test()
