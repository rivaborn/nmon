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

    def _parse_xml(self, xml_text: str) -> list[GPUSample]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise GPUSourceError(f"XML parse error: {e}") from e
        ts = time.time()
        samples = []
        for gpu in root.findall("gpu"):
            index = int(gpu.find("minor_number").text)
            uuid = gpu.find("uuid").text.strip()
            name = gpu.find("product_name").text.strip()
            temp = float(gpu.find("temperature/gpu_temp").text.split()[0])
            mem_used = float(gpu.find("fb_memory_usage/used").text.split()[0])
            mem_total = float(gpu.find("fb_memory_usage/total").text.split()[0])
            power = float(gpu.find("power_readings/power_draw").text.split()[0])
            samples.append(GPUSample(
                gpu=GPUInfo(index=index, uuid=uuid, name=name),
                timestamp=ts,
                temperature_c=temp,
                memory_used_mib=mem_used,
                memory_total_mib=mem_total,
                power_draw_w=power,
            ))
        return samples

    def list_gpus(self) -> list[GPUInfo]:
        return [s.gpu for s in self.sample_all()]

    def sample_all(self) -> list[GPUSample]:
        xml_text = self._run_smi(["--xml-format",
            "--query-gpu=gpu_name,uuid,temperature.gpu,memory.used,memory.total,power.draw"])
        return self._parse_xml(xml_text)
