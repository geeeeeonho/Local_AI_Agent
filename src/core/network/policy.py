"""Network intent only: this module never starts proxies or calls Docker."""
from dataclasses import dataclass
from enum import Enum

class NetworkMode(str, Enum):
    DIRECT = 'direct'
    WARP = 'warp'
    TOR = 'tor'
    BLOCK = 'block'


def resolve_mode(*, session=None, project=None, app=None, global_mode='warp') -> NetworkMode:
    for value in (session, project, app, global_mode):
        if value is not None:
            return NetworkMode(value)
    raise ValueError('no network mode was configured')


@dataclass(frozen=True)
class NetworkPolicy:
    mode: NetworkMode
    execution: str = 'sandbox'

    def __post_init__(self):
        object.__setattr__(self, 'mode', NetworkMode(self.mode))
        if self.execution not in ('host', 'sandbox'):
            raise ValueError('execution must be host or sandbox')
        if self.execution == 'host' and self.mode is NetworkMode.BLOCK:
            raise ValueError('Host Block is unsupported; select Sandbox for fail-closed egress')

    @property
    def public_egress(self) -> bool:
        return self.mode is not NetworkMode.BLOCK

    @property
    def search_available(self) -> bool:
        return self.public_egress

    @property
    def proxy_required(self) -> bool:
        return self.mode in (NetworkMode.WARP, NetworkMode.TOR)
