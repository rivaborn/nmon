import time
import pynvml
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.models import GPUInfo, GPUSample

class NvmlSource(GPUSource):
    def __init__(self):
        self._initialized = False

    def is_available(self) -> bool:
        try:
            pynvml.nvmlInit()
            pynvml.nvmlShutdown()
            return True
        except Exception:
            return False

    def _ensure_init(self) -> None:
        if not self._initialized:
            try:
                pynvml.nvmlInit()
                self._initialized = True
            except pynvml.NVMLError as e:
                raise GPUSourceError(str(e)) from e

    def list_gpus(self) -> list[GPUInfo]:
        return [s.gpu for s in self.sample_all()]

    def sample_all(self) -> list[GPUSample]:
        self._ensure_init()
        try:
            count = pynvml.nvmlDeviceGetCount()
            ts = time.time()
            samples = []
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                uuid = pynvml.nvmlDeviceGetUUID(handle)
                name = pynvml.nvmlDeviceGetName(handle)
                temp = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_used = mem.used / (1024 * 1024)
                mem_total = mem.total / (1024 * 1024)
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                samples.append(GPUSample(
                    gpu=GPUInfo(index=i, uuid=uuid, name=name),
                    timestamp=ts,
                    temperature_c=temp,
                    memory_used_mib=mem_used,
                    memory_total_mib=mem_total,
                    power_draw_w=power,
                ))
            return samples
        except pynvml.NVMLError as e:
            raise GPUSourceError(str(e)) from e

    def close(self) -> None:
        if self._initialized:
            pynvml.nvmlShutdown()
            self._initialized = False
