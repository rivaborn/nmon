import threading
import time
import collections
import logging
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.storage import Storage, StorageError
from nmon.models import GPUSample, AppConfig

log = logging.getLogger(__name__)

class Collector:
    def __init__(self, source: GPUSource, storage: Storage, config: AppConfig):
        self._source = source
        self._storage = storage
        self._interval = config.interval_seconds
        self._min = config.min_interval
        self._max = config.max_interval
        self._retention = config.retention_hours
        self._latest: list[GPUSample] | None = None
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
                    interval = self._interval
                self._storage.insert_samples(samples)
                self._storage.prune_old(self._retention)
            except GPUSourceError as e:
                log.warning("GPU source error: %s", e)
            except StorageError as e:
                log.error("Storage error: %s", e)
            except Exception as e:
                log.error("Unexpected error in collector: %s", e)
            with self._lock:
                interval = self._interval
            elapsed = time.monotonic() - t0
            self._stop.wait(max(0.0, interval - elapsed))
