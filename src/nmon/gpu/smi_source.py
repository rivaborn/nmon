import subprocess
import time
import xml.etree.ElementTree as ET
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.models import GPUInfo, GPUSample

class SmiSource(GPUSource):
    SMI_TIMEOUT = 5

    def is_available(self) -> bool:
        try:
            r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=3)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _run_smi(self, args: list[str]) -> str:
        try:
            r = subprocess.run(["nvidia-smi"] + args, capture_output=True,
                               text=True, timeout=self.SMI_TIMEOUT)
        except FileNotFoundError as e:
            raise GPUSourceError("nvidia-smi not found") from e
        except subprocess.TimeoutExpired as e:
            raise GPUSourceError("nvidia-smi timed out") from e
        if r.returncode != 0:
            raise GPUSourceError(r.stderr)
        return r.stdout

    @staticmethod
    def _text(node, path: str) -> str | None:
        el = node.find(path)
        if el is None or el.text is None:
            return None
        return el.text.strip()

    @classmethod
    def _num(cls, node, path: str) -> float | None:
        """Parse the leading number from a node like '72 C' / '120.00 W' /
        '4096 MiB'. Returns None for a missing element or an 'N/A' value
        (e.g. power_draw on a laptop dGPU without a power sensor)."""
        t = cls._text(node, path)
        if not t or t.upper().startswith("N/A"):
            return None
        try:
            return float(t.split()[0])
        except (ValueError, IndexError):
            return None

    def _parse_xml(self, xml_text: str) -> list[GPUSample]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise GPUSourceError(f"XML parse error: {e}") from e
        ts = time.time()
        samples = []
        # Index by enumeration order: <minor_number> is a Linux-only field
        # (reported N/A on Windows), and enumeration order matches the NVML GPU
        # indices, so it's the portable choice. Every field is parsed
        # defensively so a missing/renamed/"N/A" element degrades to 0 rather
        # than crashing the whole sample.
        for index, gpu in enumerate(root.findall("gpu")):
            uuid = self._text(gpu, "uuid") or f"GPU-{index}"
            name = self._text(gpu, "product_name") or "Unknown GPU"
            temp = self._num(gpu, "temperature/gpu_temp")
            mem_used = self._num(gpu, "fb_memory_usage/used")
            mem_total = self._num(gpu, "fb_memory_usage/total")
            # Power element naming has churned across driver versions:
            #   <power_readings><power_draw>                 (pre-535)
            #   <gpu_power_readings><power_draw>             (535+)
            #   <gpu_power_readings><instant_power_draw> /   (latest; <power_draw>
            #                       <average_power_draw>      is deprecated)
            # Try them in priority order; "N/A" entries are skipped by _num.
            power = None
            for _power_path in (
                "gpu_power_readings/instant_power_draw",
                "gpu_power_readings/average_power_draw",
                "gpu_power_readings/power_draw",
                "power_readings/instant_power_draw",
                "power_readings/average_power_draw",
                "power_readings/power_draw",
            ):
                power = self._num(gpu, _power_path)
                if power is not None:
                    break
            samples.append(GPUSample(
                gpu=GPUInfo(index=index, uuid=uuid, name=name),
                timestamp=ts,
                temperature_c=temp if temp is not None else 0.0,
                memory_used_mib=mem_used if mem_used is not None else 0.0,
                memory_total_mib=mem_total if mem_total is not None else 0.0,
                power_draw_w=power if power is not None else 0.0,
            ))
        return samples

    def list_gpus(self) -> list[GPUInfo]:
        return [s.gpu for s in self.sample_all()]

    def sample_all(self) -> list[GPUSample]:
        # `-q -x` dumps full XML for every GPU. (--query-gpu is a separate,
        # CSV-only mode that cannot be combined with XML output, which is why
        # the previous --xml-format/--query-gpu combination did not work.)
        xml_text = self._run_smi(["-q", "-x"])
        return self._parse_xml(xml_text)
