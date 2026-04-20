"""오디오 캡처 → WAV.

두 가지 모드 지원:
- **"system"** : WASAPI 루프백으로 스피커 출력(유튜브, 게임 소리 등)을 캡처.
  `soundcard` 라이브러리 사용.
- **"microphone"** : 일반 입력 장치(마이크)에서 캡처. `sounddevice` 사용.

공통 API (둘 다):
- `.start()` / `.stop()` — 녹음 제어
- `.output_path` — 저장된 WAV 파일 경로
- `.device_name` — 선택된 장치 표시용 이름
- `.peak_dbfs` — 녹음된 peak 레벨(dBFS)
- `.is_silent_output(threshold_db)` — 무음 여부 (레벨이 임계값 이하)
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


# ── 공용 유틸 ─────────────────────────────────────────────────────────────
def _peak_to_dbfs(peak: float) -> float:
    if peak <= 0:
        return -120.0
    return float(20.0 * np.log10(peak))


# ── 시스템 오디오 (WASAPI 루프백) ─────────────────────────────────────────
class SystemAudioRecorder:
    """스피커로 출력되는 소리를 캡처 (유튜브, 미디어 플레이어 등의 시스템 오디오).

    Windows에서는 `soundcard` 라이브러리가 WASAPI 루프백을 사용해 기본 스피커의
    출력 스트림을 역으로 받아온다. 이어폰/블루투스 스피커 등 현재 재생 중인
    장치면 대부분 동작한다.
    """

    def __init__(
        self,
        output_path: Path,
        *,
        samplerate: int = 44100,
        channels: int = 2,
    ) -> None:
        self.output_path = Path(output_path)
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        self.device_name: str = ""

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._error: BaseException | None = None
        self._frames_written = 0
        self._peak_abs: float = 0.0

    @property
    def frames_written(self) -> int:
        return self._frames_written

    @property
    def peak_dbfs(self) -> float:
        return _peak_to_dbfs(self._peak_abs)

    def is_silent_output(self, threshold_db: float = -80.0) -> bool:
        return self._frames_written > 0 and self.peak_dbfs < threshold_db

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("audio recorder already started")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # soundcard는 지연 임포트 — 선택 기능이므로 설치되지 않은 환경에서도
        # 마이크 모드는 계속 쓸 수 있어야 함.
        try:
            import soundcard as sc  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"시스템 오디오 캡처 모듈(soundcard) 로드 실패: {exc}"
            ) from exc

        try:
            import soundcard as sc

            speaker = sc.default_speaker()
            self.device_name = f"{speaker.name} (loopback)"
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"기본 스피커 조회 실패: {exc}") from exc

        self._stop_event.clear()
        self._frames_written = 0
        self._peak_abs = 0.0
        self._error = None

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            import soundcard as sc

            speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(
                id=str(speaker.name), include_loopback=True
            )
            block = 1024
            with loopback_mic.recorder(
                samplerate=self.samplerate, channels=self.channels, blocksize=block
            ) as rec:
                with sf.SoundFile(
                    str(self.output_path),
                    mode="w",
                    samplerate=self.samplerate,
                    channels=self.channels,
                    subtype="PCM_16",
                ) as wav:
                    while not self._stop_event.is_set():
                        data = rec.record(numframes=block)
                        if data.size == 0:
                            continue
                        wav.write(data)
                        self._frames_written += len(data)
                        peak = float(np.abs(data).max())
                        if peak > self._peak_abs:
                            self._peak_abs = peak
        except BaseException as exc:  # noqa: BLE001
            self._error = exc

    def stop(self) -> Path:
        if self._thread is None:
            raise RuntimeError("audio recorder not started")
        self._stop_event.set()
        self._thread.join()
        self._thread = None

        if self._error is not None:
            err = self._error
            self._error = None
            raise RuntimeError(f"system audio recording failed: {err}") from err

        if self._frames_written == 0:
            raise RuntimeError("no audio frames captured")

        return self.output_path


# ── 마이크 (sounddevice InputStream) ──────────────────────────────────────
@dataclass
class AudioDeviceInfo:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    default_samplerate: float

    def label(self) -> str:
        return f"{self.name} [{self.hostapi}]"


def list_input_devices() -> list[AudioDeviceInfo]:
    """sounddevice가 보는 입력 가능한 장치 목록.

    hostapi(MME/DirectSound/WASAPI 등)를 함께 표시한다.
    """
    result: list[AudioDeviceInfo] = []
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:  # noqa: BLE001
        return result

    for i, dev in enumerate(devices):
        if int(dev.get("max_input_channels", 0)) <= 0:
            continue
        hostapi_idx = int(dev.get("hostapi", 0))
        hostapi_name = ""
        if 0 <= hostapi_idx < len(hostapis):
            hostapi_name = str(hostapis[hostapi_idx].get("name", ""))
        result.append(
            AudioDeviceInfo(
                index=i,
                name=str(dev.get("name", "")).strip(),
                hostapi=hostapi_name,
                max_input_channels=int(dev.get("max_input_channels", 0)),
                default_samplerate=float(dev.get("default_samplerate", 44100.0)),
            )
        )
    return result


def resolve_device(device: int | str | None) -> int | None:
    if device is None or (isinstance(device, str) and not device.strip()):
        return None
    if isinstance(device, int):
        return device
    text = str(device).strip()
    if text.isdigit():
        return int(text)
    devs = list_input_devices()
    for d in devs:
        if d.label() == text:
            return d.index
    for d in devs:
        if d.name == text:
            return d.index
    lowered = text.lower()
    for d in devs:
        if lowered in d.name.lower():
            return d.index
    raise RuntimeError(f"오디오 입력 장치를 찾을 수 없음: {text!r}")


class MicAudioRecorder:
    """sounddevice.InputStream으로 지정 입력 장치에서 녹음."""

    def __init__(
        self,
        output_path: Path,
        *,
        samplerate: int = 44100,
        channels: int = 2,
        device: int | str | None = None,
    ) -> None:
        self.output_path = Path(output_path)
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        self.device_spec = device
        self.device_index: int | None = None
        self.device_name: str = ""

        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._writer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._error: BaseException | None = None
        self._frames_written = 0
        self._peak_abs: float = 0.0

    @property
    def frames_written(self) -> int:
        return self._frames_written

    @property
    def peak_dbfs(self) -> float:
        return _peak_to_dbfs(self._peak_abs)

    def is_silent_output(self, threshold_db: float = -80.0) -> bool:
        return self._frames_written > 0 and self.peak_dbfs < threshold_db

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("audio recorder already started")

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self.device_index = resolve_device(self.device_spec)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"오디오 입력 장치 조회 실패: {exc}") from exc

        try:
            info = sd.query_devices(self.device_index, "input")
            max_in = int(info.get("max_input_channels", 0))
            if max_in <= 0:
                raise RuntimeError("입력 채널이 없는 장치입니다")
            if self.channels > max_in:
                self.channels = max_in
            self.device_name = str(info.get("name", "")).strip()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"오디오 입력 장치 조회 실패: {exc}") from exc

        self._stop_event.clear()
        self._frames_written = 0
        self._peak_abs = 0.0
        self._error = None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        def _callback(indata, _frames, _time_info, _status):  # noqa: ANN001
            self._queue.put(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            device=self.device_index,
            dtype="float32",
            callback=_callback,
        )
        self._stream.start()

        self._writer_thread = threading.Thread(target=self._run_writer, daemon=True)
        self._writer_thread.start()

    def _run_writer(self) -> None:
        try:
            with sf.SoundFile(
                str(self.output_path),
                mode="w",
                samplerate=self.samplerate,
                channels=self.channels,
                subtype="PCM_16",
            ) as wav:
                while not (self._stop_event.is_set() and self._queue.empty()):
                    try:
                        block = self._queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    wav.write(block)
                    self._frames_written += len(block)
                    peak = float(np.abs(block).max()) if block.size else 0.0
                    if peak > self._peak_abs:
                        self._peak_abs = peak
        except BaseException as exc:  # noqa: BLE001
            self._error = exc

    def stop(self) -> Path:
        if self._stream is None:
            raise RuntimeError("audio recorder not started")

        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None

        self._stop_event.set()
        if self._writer_thread is not None:
            self._writer_thread.join()
            self._writer_thread = None

        if self._error is not None:
            err = self._error
            self._error = None
            raise RuntimeError(f"audio recording failed: {err}") from err

        if self._frames_written == 0:
            raise RuntimeError("no audio frames captured")

        return self.output_path


# 이전 버전 호환을 위한 별칭 (외부에서 AudioRecorder로 임포트하던 코드가 깨지지 않도록)
AudioRecorder = MicAudioRecorder
