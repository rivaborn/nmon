from dataclasses import dataclass
from typing import TypedDict, Literal

@dataclass(frozen=True)
class GPUInfo:
    index: int
    uuid: str
    name: str

@dataclass
class GPUSample:
    gpu: GPUInfo
    timestamp: float
    temperature_c: float
    memory_used_mib: float
    memory_total_mib: float
    power_draw_w: float

    @property
    def memory_fraction(self) -> float:
        if self.memory_total_mib == 0:
            return 0.0
        return self.memory_used_mib / self.memory_total_mib

@dataclass
class GPUStats:
    gpu: GPUInfo
    current: GPUSample
    max_temp_24h: float
    avg_temp_1h: float

class HistoryRow(TypedDict):
    timestamp: float
    value: float

@dataclass
class AppConfig:
    interval_seconds: int
    min_interval: int
    max_interval: int
    db_path: str
    retention_hours: int
    default_tab: str
    default_time_window_hours: int

def sample_to_row(sample: GPUSample) -> dict:
    return {
        "gpu_index": sample.gpu.index,
        "gpu_uuid": sample.gpu.uuid,
        "gpu_name": sample.gpu.name,
        "timestamp": sample.timestamp,
        "temperature_c": sample.temperature_c,
        "memory_used_mib": sample.memory_used_mib,
        "memory_total_mib": sample.memory_total_mib,
        "power_draw_w": sample.power_draw_w,
    }

def row_to_sample(row) -> GPUSample:
    # row is a sqlite3.Row or dict with the same keys as sample_to_row output
    gpu = GPUInfo(index=row["gpu_index"], uuid=row["gpu_uuid"], name=row["gpu_name"])
    return GPUSample(
        gpu=gpu,
        timestamp=row["timestamp"],
        temperature_c=row["temperature_c"],
        memory_used_mib=row["memory_used_mib"],
        memory_total_mib=row["memory_total_mib"],
        power_draw_w=row["power_draw_w"],
    )
