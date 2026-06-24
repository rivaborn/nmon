import threading
import time
import collections
import logging
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.storage import Storage, StorageError
from nmon.models import GPUSample, AppConfig, OllamaSample, VLLMSample
from nmon.ollama import OllamaClient
from nmon.vllm import VLLMClient

log = logging.getLogger(__name__)

class Collector:
    # When an LLM server poll fails (or the startup probe didn't find it),
    # wait this long before trying again instead of probing every tick.
    # Keeps idle CPU low when a server is permanently absent while still
    # picking up servers that come online after nmon started.
    REDETECT_INTERVAL_SECONDS = 60.0

    def __init__(
        self,
        source: GPUSource,
        storage: Storage,
        config: AppConfig,
        ollama: OllamaClient | None = None,
        vllm: VLLMClient | None = None,
        ollama_reachable_at_start: bool = True,
        vllm_reachable_at_start: bool = True,
    ):
        self._source = source
        self._storage = storage
        self._interval = config.interval_seconds
        self._min = config.min_interval
        self._max = config.max_interval
        self._retention = config.retention_hours
        self._latest: list[GPUSample] | None = None
        self._ollama = ollama
        self._latest_ollama: OllamaSample | None = None
        self._vllm = vllm
        self._latest_vllm: VLLMSample | None = None
        # monotonic deadlines: a poll is skipped until time.monotonic() reaches this.
        # Seeded from the startup probe — if a server was missing at launch we delay
        # the first attempt by REDETECT_INTERVAL_SECONDS so the collector doesn't
        # immediately re-try on the very next tick.
        now_mono = time.monotonic()
        self._ollama_next_attempt: float = (
            0.0 if ollama_reachable_at_start else now_mono + self.REDETECT_INTERVAL_SECONDS
        )
        self._vllm_next_attempt: float = (
            0.0 if vllm_reachable_at_start else now_mono + self.REDETECT_INTERVAL_SECONDS
        )
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_gpu_count: int | None = None
        self.warnings: collections.deque = collections.deque(maxlen=50)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def get_latest(self) -> list[GPUSample] | None:
        with self._lock:
            return self._latest

    def get_latest_ollama(self) -> OllamaSample | None:
        with self._lock:
            return self._latest_ollama

    def get_latest_vllm(self) -> VLLMSample | None:
        with self._lock:
            return self._latest_vllm

    def set_interval(self, seconds: int) -> None:
        with self._lock:
            self._interval = max(self._min, min(self._max, seconds))

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                samples = self._source.sample_all()
                count = len(samples)
                if self._last_gpu_count is not None and count != self._last_gpu_count:
                    msg = f"GPU count changed: {self._last_gpu_count} -> {count}"
                    log.warning(msg)
                    self.warnings.append(msg)
                self._last_gpu_count = count
                with self._lock:
                    self._latest = samples
                self._storage.insert_samples(samples)
                self._storage.prune_old(self._retention)
            except GPUSourceError as e:
                log.warning("GPU source error: %s", e)
            except StorageError as e:
                log.error("Storage error: %s", e)
            except Exception as e:
                log.error("Unexpected error in collector: %s", e)

            if self._ollama is not None:
                try:
                    self._poll_ollama()
                except Exception as e:
                    log.warning("Ollama poll error: %s", e)

            if self._vllm is not None:
                try:
                    self._poll_vllm()
                except Exception as e:
                    log.warning("vLLM poll error: %s", e)

            with self._lock:
                interval = self._interval
            elapsed = time.monotonic() - t0
            self._stop.wait(max(0.0, interval - elapsed))

    def _poll_ollama(self) -> None:
        now_mono = time.monotonic()
        if now_mono < self._ollama_next_attempt:
            return  # in re-detection cooldown
        status = self._ollama.get_running() if self._ollama else None
        if status is None:
            # Unreachable: back off for REDETECT_INTERVAL_SECONDS.
            self._ollama_next_attempt = now_mono + self.REDETECT_INTERVAL_SECONDS
            with self._lock:
                self._latest_ollama = None
            return
        # Reachable: clear any pending cooldown so we keep polling every tick.
        self._ollama_next_attempt = 0.0
        sample = OllamaSample(
            timestamp=time.time(),
            running=status.running,
            model_name=status.model_name,
            size_bytes=status.size_bytes,
            size_vram_bytes=status.size_vram_bytes,
            gpu_pct=status.gpu_pct,
            cpu_pct=status.cpu_pct,
        )
        with self._lock:
            self._latest_ollama = sample
        if status.running:
            try:
                self._storage.insert_ollama_sample(sample)
                self._storage.prune_old_ollama(self._retention)
            except StorageError as e:
                log.error("Ollama storage error: %s", e)

    def _poll_vllm(self) -> None:
        now_mono = time.monotonic()
        if now_mono < self._vllm_next_attempt:
            return  # in re-detection cooldown
        status = self._vllm.get_running() if self._vllm else None
        if status is None:
            # Unreachable: back off for REDETECT_INTERVAL_SECONDS.
            self._vllm_next_attempt = now_mono + self.REDETECT_INTERVAL_SECONDS
            with self._lock:
                self._latest_vllm = None
            return
        # Reachable: clear any pending cooldown so we keep polling every tick.
        self._vllm_next_attempt = 0.0
        sample = VLLMSample(
            timestamp=time.time(),
            running=status.running,
            model_name=status.model_name,
        )
        with self._lock:
            self._latest_vllm = sample
