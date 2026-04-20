"""5sec_video 진입점 — 시스템 트레이 통합.

흐름:
- 트레이 아이콘 대기
- 트레이 아이콘 좌클릭 또는 메뉴의 "영역 지정" → 오버레이 표시 (이미 영역이 있어도 초기화 후 재지정)
- 영역 선택 완료 → 컨트롤 바 표시
- 컨트롤 바의 ● Rec → ScreenRecorder 시작, ■ Stop → 정지 후 mp4 저장
- 트레이 메뉴: 영역 지정 / 설정 / 종료
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from src.compressor import compress_mp4_async
from src.config import AppConfig, load_config, resolve_output_path
from src.controller import ControllerBar
from src.overlay import RegionSelector
from src.recorder import Region, ScreenRecorder
from src.settings_dialog import SettingsDialog


def _make_tray_icon() -> QIcon:
    """간단한 빨간 원 아이콘 생성 (외부 리소스 없이 동작하도록)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor(200, 50, 50))
    painter.setPen(QColor(255, 255, 255))
    painter.drawEllipse(8, 8, 48, 48)
    painter.end()
    return QIcon(pix)


class _CompressionSignals(QObject):
    """백그라운드 스레드 → Qt 메인 스레드로 결과를 전달하는 신호."""

    done = Signal(str, int, int)  # out_path, original_size, compressed_size
    failed = Signal(str)  # error message


class App:
    def __init__(self, qt_app: QApplication) -> None:
        self.qt_app = qt_app
        self.config: AppConfig = load_config()

        self.selector: RegionSelector | None = None
        self.controller: ControllerBar | None = None
        self.recorder: ScreenRecorder | None = None
        self.region: Region | None = None
        self.current_output: Path | None = None

        self._compress_signals = _CompressionSignals()
        self._compress_signals.done.connect(self._on_compress_done)
        self._compress_signals.failed.connect(self._on_compress_failed)

        self.tray = QSystemTrayIcon(_make_tray_icon())
        self.tray.setToolTip("5sec_video — 클릭하여 영역 지정")
        self.tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        act_select = QAction("영역 지정", menu)
        act_select.triggered.connect(self._start_region_selection)
        act_settings = QAction("설정...", menu)
        act_settings.triggered.connect(self._open_settings)
        act_quit = QAction("종료", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_select)
        menu.addAction(act_settings)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    # ── 트레이 ────────────────────────────────────────────────────────────
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._start_region_selection()

    # ── 영역 선택 ─────────────────────────────────────────────────────────
    def _start_region_selection(self) -> None:
        # 녹화 중에는 무시
        if self.recorder is not None:
            return

        # 기존 컨트롤 바가 떠 있으면 닫고 영역 초기화 (재지정 동작)
        if self.controller is not None:
            self.controller.close()
            self.controller = None
        self.region = None

        self.selector = RegionSelector()
        self.selector.selected.connect(self._on_region_selected)
        self.selector.cancelled.connect(self._on_region_cancelled)
        self.selector.show()
        self.selector.raise_()
        self.selector.activateWindow()

    def _on_region_selected(self, region: Region) -> None:
        self.region = region
        self.selector = None
        self._show_controller(region)

    def _on_region_cancelled(self) -> None:
        self.selector = None

    # ── 컨트롤 바 ─────────────────────────────────────────────────────────
    def _show_controller(self, region: Region) -> None:
        bar = ControllerBar(default_fps=self.config.fps)
        bar.start_requested.connect(self._start_recording)
        bar.stop_requested.connect(self._stop_recording)
        bar.close_requested.connect(self._on_controller_closed)

        # 물리 픽셀 → 논리 좌표로 환산해서 컨트롤 바 위치 지정
        screen = (
            QGuiApplication.screenAt(QPoint(region.x, region.y))
            or QGuiApplication.primaryScreen()
        )
        ratio = screen.devicePixelRatio() or 1.0
        bar.place_near(QPoint(int(region.x / ratio), int(region.y / ratio)))
        bar.show()
        bar.raise_()
        self.controller = bar

    def _on_controller_closed(self) -> None:
        # 녹화 중이면 정지
        if self.recorder is not None:
            self._stop_recording()
        self.controller = None
        self.region = None

    # ── 녹화 ──────────────────────────────────────────────────────────────
    def _start_recording(self, fps: int) -> None:
        if self.region is None or self.recorder is not None:
            return
        try:
            output = resolve_output_path(self.config.save_dir, self.config.filename_template)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(None, "5sec_video", f"저장 경로 생성 실패:\n{exc}")
            return

        try:
            self.recorder = ScreenRecorder(
                region=self.region,
                fps=fps,
                output_path=output,
                audio_enabled=self.config.audio_enabled,
                audio_source=self.config.audio_source,
                audio_device=self.config.audio_device or None,
            )
            self.recorder.start()
        except Exception as exc:  # noqa: BLE001
            self.recorder = None
            QMessageBox.critical(None, "5sec_video", f"녹화 시작 실패:\n{exc}")
            return

        if self.recorder.audio_error:
            # 오디오 시작 실패는 치명적이지 않음 — 트레이 알림으로만 알림
            self.tray.showMessage(
                "5sec_video",
                f"오디오 시작 실패 — 영상만 녹화됩니다.\n{self.recorder.audio_error}",
                QSystemTrayIcon.MessageIcon.Warning,
                4000,
            )

        self.current_output = output
        if self.controller is not None:
            self.controller.set_recording(True)
        audio_tag = ""
        if self.config.audio_enabled and self.recorder.audio_error is None:
            audio_tag = " +sys audio" if self.config.audio_source == "system" else " +mic"
        self.tray.setToolTip(f"5sec_video — 녹화 중 ({fps}fps{audio_tag})")

    def _stop_recording(self) -> None:
        if self.recorder is None:
            return
        recorder = self.recorder
        try:
            out = recorder.stop()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(None, "5sec_video", f"녹화 정지 실패:\n{exc}")
        else:
            size_mb = out.stat().st_size / (1024 * 1024)
            note = ""
            if recorder.mux_error:
                note = "\n(오디오 muxing 실패 — 영상만 저장됨)"
            elif recorder.audio_error and self.config.audio_enabled:
                note = "\n(오디오 캡처 실패 — 영상만 저장됨)"
            elif (
                self.config.audio_enabled
                and not recorder.audio_error
                and recorder.audio_silent
            ):
                note = (
                    f"\n(경고: 오디오 무음 감지 — peak {recorder.audio_peak_dbfs:.1f} dBFS. "
                    "시스템 오디오는 기본 스피커로 소리가 재생 중이어야 캡처됩니다.)"
                )
            self.tray.showMessage(
                "5sec_video",
                f"저장됨: {out}\n({size_mb:.1f} MB){note}",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            print(f"[5sec_video] saved: {out} ({size_mb:.1f} MB){note}")

            if self.config.auto_compress:
                self._start_compression(out)
        finally:
            self.recorder = None
            self.current_output = None
            self.tray.setToolTip("5sec_video — 클릭하여 영역 지정")
            if self.controller is not None:
                self.controller.set_recording(False)

    # ── 압축 ──────────────────────────────────────────────────────────────
    def _start_compression(self, path: Path) -> None:
        self.tray.showMessage(
            "5sec_video",
            f"압축 중... ({path.name})",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )
        signals = self._compress_signals

        def _on_success(out: Path, original: int, compressed: int) -> None:
            signals.done.emit(str(out), original, compressed)

        def _on_error(exc: BaseException) -> None:
            signals.failed.emit(str(exc))

        compress_mp4_async(
            path,
            on_success=_on_success,
            on_error=_on_error,
        )

    def _on_compress_done(self, out_path: str, original: int, compressed: int) -> None:
        orig_mb = original / (1024 * 1024)
        comp_mb = compressed / (1024 * 1024)
        ratio = (compressed / original) if original > 0 else 1.0
        self.tray.showMessage(
            "5sec_video",
            f"압축 완료: {Path(out_path).name}\n"
            f"{orig_mb:.1f} MB → {comp_mb:.1f} MB ({ratio * 100:.0f}%)",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )
        print(f"[5sec_video] compressed: {out_path} ({orig_mb:.1f} → {comp_mb:.1f} MB)")

    def _on_compress_failed(self, message: str) -> None:
        self.tray.showMessage(
            "5sec_video",
            f"압축 실패 — 원본은 그대로 유지됩니다.\n{message}",
            QSystemTrayIcon.MessageIcon.Warning,
            4000,
        )
        print(f"[5sec_video] compress failed: {message}")

    # ── 설정 / 종료 ───────────────────────────────────────────────────────
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config)
        if dlg.exec():
            self.config = dlg.updated_config()

    def _quit(self) -> None:
        if self.recorder is not None:
            try:
                self.recorder.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.controller is not None:
            self.controller.close()
        self.tray.hide()
        self.qt_app.quit()


def main() -> None:
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "5sec_video", "시스템 트레이를 사용할 수 없습니다.")
        sys.exit(1)

    app = App(qt_app)  # 변수에 보관하지 않으면 GC되어 트레이가 사라짐
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
