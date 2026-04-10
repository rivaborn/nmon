"""Minimal NVAPI wrapper for reading GPU memory junction (VRAM) temperature.

Used as a fallback on Windows when NVML's NVML_FI_DEV_MEMORY_TEMP field
returns NVML_ERROR_NOT_SUPPORTED -- the common case on consumer GeForce
cards like the RTX 3090. Calls the undocumented but widely-used
NvAPI_GPU_ClientThermalSensors_GetValues function (id 0x65FE3AAD), which
is the same entry point HWiNFO / GPU-Z use to surface GDDR6X temperatures.

All failures degrade to returning None, so callers can treat the sensor
as unsupported without crashing the collector.

Run diagnostics with:
    python -m nmon.gpu.nvapi
"""

import ctypes
import logging
import sys
import threading

log = logging.getLogger(__name__)

# NVAPI function IDs. The first three are public; the thermal sensors id
# is undocumented but has been stable across Ampere / Ada / Blackwell drivers.
_NVAPI_INITIALIZE = 0x0150E828
_NVAPI_UNLOAD = 0xD22BDD7E
_NVAPI_ENUM_PHYSICAL_GPUS = 0xE5AC921F
_NVAPI_GPU_GET_THERMAL_SETTINGS = 0xE3640A56
_NVAPI_GPU_CLIENT_THERMAL_SENSORS_GET_VALUES = 0x65FE3AAD

# Values for NV_GPU_THERMAL_SETTINGS.sensor[i].target
_THERMAL_TARGET_NAMES = {
    0: "NONE",
    1: "GPU",
    2: "MEMORY",
    4: "POWER_SUPPLY",
    8: "BOARD",
    9: "VCD_BOARD",
    10: "VCD_INLET",
    11: "VCD_OUTLET",
    15: "ALL",
}
_THERMAL_TARGET_ALL = 15
_NVAPI_MAX_THERMAL_SENSORS_PER_GPU = 3

_NVAPI_MAX_PHYSICAL_GPUS = 64
_NVAPI_OK = 0

# Channel indices on Ampere / Ada consumer cards. Index 0 is always the
# GPU core sensor; index 1 is consistently the GPU Hot Spot (hottest
# point on the die) on every tested card. Index 9 holds the GDDR6X
# memory junction on cards that expose it (RTX 3080 / 3090 / 4080 /
# 4090). If a card reports a clearly hotter channel at a different
# index, update _SENSOR_INDEX_MEMORY after running the diagnostic.
_SENSOR_INDEX_HOTSPOT = 1
_SENSOR_INDEX_MEMORY = 9


class _NvGpuClientThermalSensors(ctypes.Structure):
    """Layout matching NV_GPU_CLIENT_THERMAL_SENSORS v2 (168 bytes).

    Temperatures are reported in milli-degrees Celsius.
    """
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("mask", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 8),
        ("temperatures", ctypes.c_int32 * 32),
    ]


class _NvThermalSensor(ctypes.Structure):
    """One entry in NV_GPU_THERMAL_SETTINGS.sensor[]."""
    _fields_ = [
        ("controller", ctypes.c_uint32),
        ("defaultMinTemp", ctypes.c_int32),
        ("defaultMaxTemp", ctypes.c_int32),
        ("currentTemp", ctypes.c_int32),
        ("target", ctypes.c_uint32),
    ]


class _NvGpuThermalSettings(ctypes.Structure):
    """Layout matching NV_GPU_THERMAL_SETTINGS v2 (68 bytes).

    Documented NVAPI struct. currentTemp is in whole °C.
    """
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("count", ctypes.c_uint32),
        ("sensor", _NvThermalSensor * _NVAPI_MAX_THERMAL_SENSORS_PER_GPU),
    ]


_V2_STRUCT_SIZE = ctypes.sizeof(_NvGpuClientThermalSensors)
_V2_VERSION = _V2_STRUCT_SIZE | (2 << 16)

_THERMAL_SETTINGS_SIZE = ctypes.sizeof(_NvGpuThermalSettings)
_THERMAL_SETTINGS_VERSION = _THERMAL_SETTINGS_SIZE | (2 << 16)


_lock = threading.Lock()
_state = {
    "init_tried": False,
    "initialized": False,
    "query_iface": None,
    "gpu_handles": [],
    "fn_cache": {},
    "unsupported_gpus": set(),
}


def _load_and_init() -> bool:
    """Lazily load nvapi64.dll and call NvAPI_Initialize. Idempotent."""
    if _state["initialized"]:
        return True
    if _state["init_tried"]:
        return False
    _state["init_tried"] = True

    if sys.platform != "win32":
        log.debug("NVAPI: not on Windows, skipping")
        return False

    try:
        dll = ctypes.WinDLL("nvapi64.dll")
    except (OSError, AttributeError) as e:
        log.debug("NVAPI: nvapi64.dll not available: %s", e)
        return False

    try:
        query = dll.nvapi_QueryInterface
    except AttributeError:
        log.debug("NVAPI: nvapi_QueryInterface export missing")
        return False

    query.restype = ctypes.c_void_p
    query.argtypes = [ctypes.c_uint32]
    _state["query_iface"] = query

    init_proto = ctypes.CFUNCTYPE(ctypes.c_int32)
    addr = query(_NVAPI_INITIALIZE)
    if not addr:
        log.debug("NVAPI: could not resolve NvAPI_Initialize")
        return False
    init_fn = init_proto(addr)
    status = init_fn()
    if status != _NVAPI_OK:
        log.debug("NVAPI: NvAPI_Initialize returned %d", status)
        return False

    _state["initialized"] = True
    return True


def _resolve(fn_id: int, prototype):
    """Resolve and cache an NVAPI function pointer by id."""
    cache = _state["fn_cache"]
    if fn_id in cache:
        return cache[fn_id]
    addr = _state["query_iface"](fn_id)
    if not addr:
        cache[fn_id] = None
        return None
    fn = prototype(addr)
    cache[fn_id] = fn
    return fn


def _enum_gpus() -> bool:
    if _state["gpu_handles"]:
        return True
    proto = ctypes.CFUNCTYPE(
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    )
    fn = _resolve(_NVAPI_ENUM_PHYSICAL_GPUS, proto)
    if fn is None:
        return False
    handles = (ctypes.c_void_p * _NVAPI_MAX_PHYSICAL_GPUS)()
    count = ctypes.c_uint32(0)
    status = fn(handles, ctypes.byref(count))
    if status != _NVAPI_OK:
        log.debug("NVAPI: NvAPI_EnumPhysicalGPUs returned %d", status)
        return False
    _state["gpu_handles"] = [
        ctypes.c_void_p(handles[i]) for i in range(count.value)
    ]
    return True


# Sensor-channel masks to try, widest first. 0x3FF asks for 10 channels
# (enough to reach the GDDR6X memory junction at index 9); 0xFF covers
# the 8 channels observed on cards without a dedicated memory sensor.
# The driver rejects masks that ask for channels the card doesn't have,
# so we fall through to narrower masks.
_SENSOR_MASKS = (0xFFFF, 0x3FF, 0x1FF, 0xFF, 0x1F, 0x0F, 0x03, 0x01)

# Temperatures are reported in Q8.8 fixed point: upper 8 bits are whole
# degrees C, lower 8 bits are fractional. Verified by cross-referencing
# against the documented NvAPI_GPU_GetThermalSettings GPU core temp.
_TEMP_DIVISOR = 256.0


def _read_thermal_sensors(gpu_index: int):
    """Read the raw thermal sensors struct for a GPU. Returns the struct
    or None if the call path fails at any stage."""
    if not _load_and_init():
        return None
    if not _enum_gpus():
        return None
    handles = _state["gpu_handles"]
    if gpu_index >= len(handles):
        return None
    proto = ctypes.CFUNCTYPE(
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.POINTER(_NvGpuClientThermalSensors),
    )
    fn = _resolve(_NVAPI_GPU_CLIENT_THERMAL_SENSORS_GET_VALUES, proto)
    if fn is None:
        return None
    for mask in _SENSOR_MASKS:
        data = _NvGpuClientThermalSensors()
        data.version = _V2_VERSION
        data.mask = mask
        try:
            status = fn(handles[gpu_index], ctypes.byref(data))
        except OSError as e:
            log.debug("NVAPI: thermal sensors call raised: %s", e)
            return None
        if status == _NVAPI_OK:
            return data
        log.debug("NVAPI: mask=0x%x returned %d", mask, status)
    return None


def read_thermal_channels(gpu_index: int) -> dict[str, float] | None:
    """Read the GPU hotspot and memory junction temperatures via NVAPI.

    Returns a dict with some subset of the keys "hotspot" and "memory"
    (values in degrees C), or None if NVAPI is entirely unavailable or
    the thermal channels call fails for all masks. A GPU that succeeds
    on the call but has no populated value at the requested index is
    simply omitted from the dict — the caller gets an empty dict back,
    which we also turn into None to signal "nothing useful".

    Once a GPU fails entirely it is cached as unsupported so we don't
    keep paying for the round trip every sample.
    """
    with _lock:
        if gpu_index in _state["unsupported_gpus"]:
            return None
        data = _read_thermal_sensors(gpu_index)
        if data is None:
            _state["unsupported_gpus"].add(gpu_index)
            return None
        result: dict[str, float] = {}
        hotspot_raw = data.temperatures[_SENSOR_INDEX_HOTSPOT]
        if hotspot_raw > 0:
            result["hotspot"] = hotspot_raw / _TEMP_DIVISOR
        memory_raw = data.temperatures[_SENSOR_INDEX_MEMORY]
        if memory_raw > 0:
            result["memory"] = memory_raw / _TEMP_DIVISOR
        if not result:
            _state["unsupported_gpus"].add(gpu_index)
            return None
        return result


def _probe_and_label_channels(gpu_index: int, core_temp: int | None) -> None:
    """Read the undocumented thermal channels and label each populated
    channel by comparing its value against the documented GPU core
    temp. Flags the current production indices for hotspot and memory
    junction so it's easy to see whether they're wired on this card."""
    data = _read_thermal_sensors(gpu_index)
    if data is None:
        print("  client thermal channels: call failed for all masks")
        return
    print(f"  client thermal channels: mask=0x{data.mask:08x}"
          f" (Q8.8 fixed point, divide raw by 256)")
    any_sensor = False
    for j in range(32):
        raw = data.temperatures[j]
        if raw == 0:
            continue
        any_sensor = True
        temp = raw / _TEMP_DIVISOR
        tags = []
        if j == _SENSOR_INDEX_HOTSPOT:
            tags.append("[HOTSPOT used by nmon]")
        if j == _SENSOR_INDEX_MEMORY:
            tags.append("[MEMORY JUNCTION used by nmon]")
        if core_temp is not None:
            diff = temp - core_temp
            if abs(diff) <= 2:
                tags.append("matches GPU core")
            elif diff > 2:
                tags.append(f"core {diff:+.1f}C (hotter than core)")
            else:
                tags.append(f"core {diff:+.1f}C")
        suffix = ("  <-- " + " | ".join(tags)) if tags else ""
        print(f"    sensor[{j:2d}] = {temp:6.2f}C  (raw {raw}){suffix}")
    if not any_sensor:
        print("    (no populated sensors)")
    print()
    print("  Channel roles on tested Ampere/Ada cards:")
    print("    index 0 = GPU core (same as documented path)")
    print(f"    index {_SENSOR_INDEX_HOTSPOT} = GPU hotspot (hottest point on the die)")
    print(f"    index {_SENSOR_INDEX_MEMORY} = GPU memory junction (GDDR6X sensor)")
    print("  If a clearly hotter channel appears at a different index on")
    print("  your card, update _SENSOR_INDEX_HOTSPOT or _SENSOR_INDEX_MEMORY")
    print("  in src/nmon/gpu/nvapi.py.")


def _probe_documented_thermal_settings(gpu_index: int) -> int | None:
    """Call the documented NvAPI_GPU_GetThermalSettings and print all
    sensors it reports. Returns the GPU core temperature (whole degrees
    C) if the call succeeds, so the caller can cross-reference it
    against the undocumented client thermal channels."""
    proto = ctypes.CFUNCTYPE(
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_NvGpuThermalSettings),
    )
    fn = _resolve(_NVAPI_GPU_GET_THERMAL_SETTINGS, proto)
    if fn is None:
        print("  documented NvAPI_GPU_GetThermalSettings: not resolvable")
        return None
    data = _NvGpuThermalSettings()
    data.version = _THERMAL_SETTINGS_VERSION
    handle = _state["gpu_handles"][gpu_index]
    status = fn(handle, _THERMAL_TARGET_ALL, ctypes.byref(data))
    if status != _NVAPI_OK:
        print(f"  documented NvAPI_GPU_GetThermalSettings: returned {status}")
        return None
    print(f"  documented sensors: count={data.count}")
    gpu_core_temp = None
    for j in range(min(data.count, _NVAPI_MAX_THERMAL_SENSORS_PER_GPU)):
        s = data.sensor[j]
        target_name = _THERMAL_TARGET_NAMES.get(s.target, f"?({s.target})")
        print(f"    [{j}] target={target_name:14s}"
              f" current={s.currentTemp}C"
              f" range=[{s.defaultMinTemp},{s.defaultMaxTemp}]")
        if s.target == 1 and gpu_core_temp is None:  # NVAPI_THERMAL_TARGET_GPU
            gpu_core_temp = s.currentTemp
    return gpu_core_temp


def diagnostic() -> None:
    """Dump every populated thermal sensor for every visible GPU.

    Use this to verify NVAPI is working and to identify which sensor
    index maps to memory junction on a given card.
    """
    if sys.platform != "win32":
        print("NVAPI: Windows-only, skipping.")
        return
    with _lock:
        if not _load_and_init():
            print("NVAPI: failed to load or initialize nvapi64.dll.")
            return
        if not _enum_gpus():
            print("NVAPI: failed to enumerate GPUs.")
            return
        handles = _state["gpu_handles"]
        print(f"NVAPI: found {len(handles)} GPU(s).")
        print(f"NVAPI: client thermal sensors version tag = 0x{_V2_VERSION:08x}"
              f" (size={_V2_STRUCT_SIZE})")
        print(f"NVAPI: documented thermal settings version tag ="
              f" 0x{_THERMAL_SETTINGS_VERSION:08x}"
              f" (size={_THERMAL_SETTINGS_SIZE})")
        for i in range(len(handles)):
            print(f"\nGPU {i}:")
            core_temp = _probe_documented_thermal_settings(i)
            _probe_and_label_channels(i, core_temp)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    diagnostic()
