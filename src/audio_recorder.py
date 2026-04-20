"""오디오(마이크) 캡처 → WAV 파일.

- sounddevice.InputStream으로 기본 입력 장치(또는 지정 장치)에서 오디오 캡처
- 콜백 → Queue → writer 스레드에서 soundfile로 WAV 기록 (PCM_16)
- start() / stop()으로 제어. stop()은 WAV 경로를 반환.
- 장치가 2채널을 지원하지 않으면 자동으로 mono로 폴백.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


class AudioRecorder:
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
        self.device = device

        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._writer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._error: BaseException | None = None
        self._frames_written = 0

    @property
    def frames_written(self) -> int:
        return self._frames_written

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("audio recorder already started")

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # 장치가 요청한 채널 수를 지원하지 않으면 가능한 최대값으로 축소 (mono 폴백 포함)
        try:
            info = sd.query_devices(self.device, "input")
            max_in = int(info.get("max_input_channels", 0))
            if max_in <= 0:
                raise RuntimeError("입력 채널이 없는 장치입니다")
            if self.channels > max_in:
                self.channels = max_in
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"오디오 입력 장치 조회 실패: {exc}") from exc

        self._stop_event.clear()
        self._frames_written = 0
        self._error = None
        # 이전 실행의 잔재가 있으면 비움
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        def _callback(indata, _frames, _time_info, _status):  # noqa: ANN001
            # 스트림 버퍼와 분리하기 위해 복사
            self._queue.put(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            device=self.device,
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
