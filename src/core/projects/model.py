"""Project linkage, not a copy of AnythingLLM documents or Interpreter sessions."""
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
import re
from core.network.policy import NetworkMode

@dataclass(frozen=True)
class Project:
    id: str
    name: str
    workspace_path: str
    anythingllm_workspace: str = ''
    chat_model: str = ''
    agent_model: str = ''
    network_mode: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        if not isinstance(self.id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', self.id):
            raise ValueError('invalid project id')
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('project name must not be empty')
        for field in ('workspace_path', 'anythingllm_workspace', 'chat_model', 'agent_model'):
            if not isinstance(getattr(self, field), str):
                raise ValueError(f'{field} must be a string')
        if not (Path(self.workspace_path).is_absolute() or PureWindowsPath(self.workspace_path).is_absolute()):
            raise ValueError('workspace_path must be absolute')
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('unsupported project schema_version')
        if self.network_mode is not None:
            NetworkMode(self.network_mode)

    def to_dict(self) -> dict:
        return asdict(self)
