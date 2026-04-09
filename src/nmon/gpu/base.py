from abc import ABC, abstractmethod
from nmon.models import GPUInfo, GPUSample

class GPUSourceError(RuntimeError): pass

class GPUSource(ABC):
    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def list_gpus(self) -> list[GPUInfo]: ...

    @abstractmethod
    def sample_all(self) -> list[GPUSample]: ...

    def close(self) -> None:
        pass
