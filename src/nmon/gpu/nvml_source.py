import time
import pynvml
from nmon.gpu import nvapi
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.models import GPUInfo, GPUSample

class NvmlSource(GPUSource):
    def __init__(self):
        self._initialized = False
        # Per-GPU caches so we don't re-probe unsupported paths every sample.
        self._nvml_mem_unsupported: set[int] = set()

    def _read_nvml_memory_temp(self, index: int, handle) -> float | None:
        """Try NVML's documented memory temperature field. Works on
        data-center GPUs, almost never on consumer GeForce."""
        if index in self._nvml_mem_unsupported:
            return None
        try:
            values = pynvml.nvmlDeviceGetFieldValues(
                handle, [pynvml.NVML_FI_DEV_MEMORY_TEMP]
            )
            if values and values[0].nvmlReturn == 0:
                return float(values[0].value.siVal)
        except Exception:
            pass
        self._nvml_mem_unsupported.add(index)
        return None

    def _read_extra_temps(
        self, index: int, handle
    ) -> tuple[float | None, float | None]:
        """Returns (hotspot_c, memory_junction_c) for the given GPU.

        Hotspot comes only from NVAPI (there's no NVML equivalent).
        Memory junction tries NVML first, then falls back to NVAPI.
        """
        nvml_mem = self._read_nvml_memory_temp(index, handle)
        nvapi_channels = nvapi.read_thermal_channels(index) or {}
        hotspot = nvapi_channels.get("hotspot")
        memory = nvml_mem if nvml_mem is not None else nvapi_channels.get("memory")
        return hotspot, memory

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
                hotspot, junction = self._read_extra_temps(i, handle)
                samples.append(GPUSample(
                    gpu=GPUInfo(index=i, uuid=uuid, name=name),
                    timestamp=ts,
                    temperature_c=temp,
                    memory_used_mib=mem_used,
                    memory_total_mib=mem_total,
                    power_draw_w=power,
                    hotspot_temp_c=hotspot,
                    memory_junction_temp_c=junction,
                ))
            return samples
        except pynvml.NVMLError as e:
            raise GPUSourceError(str(e)) from e

    def close(self) -> None:
        if self._initialized:
            pynvml.nvmlShutdown()
            self._initialized = False
