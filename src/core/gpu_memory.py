"""Read-only NVIDIA VRAM budget estimate for explicit model-start choices.

No package imports, no GPU initialization and no sampling on the Studio idle loop.
A loaded Ollama model already occupies VRAM: never treat reported free memory as
the capacity available *after unloading* it.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Optional


@dataclass(frozen=True)
class GpuMemory:
    total_gib: float
    free_gib: float

    @property
    def reserve_gib(self) -> float:
        # Leave space for display, KV cache and intermediate buffers.
        # It is a heuristic, not a guarantee that a model fits.
        return max(1.5, self.total_gib * 0.10)

    @property
    def budget_gib(self) -> float:
        return max(0.0, self.free_gib - self.reserve_gib)


def parse_nvidia_smi(output: str) -> Optional[GpuMemory]:
    """Parse memory.total,memory.free (MiB); choose the best individual GPU."""
    valid = []
    for line in str(output).splitlines():
        fields = [part.strip() for part in line.split(',')]
        if len(fields) != 2:
            continue
        try:
            total, free = (float(value) for value in fields)
        except ValueError:
            continue
        if not (0 < total and 0 <= free <= total):
            continue
        valid.append(GpuMemory(total / 1024.0, free / 1024.0))
    return max(valid, key=lambda item: item.free_gib) if valid else None


def detect_gpu_memory(timeout: float = 3.0) -> Optional[GpuMemory]:
    """Best-effort NVIDIA snapshot; unsupported GPUs return None.

    Never start an LLM or use CUDA merely to examine capacity. We do not sum
    multiple GPUs, because a model spanning them is a different placement case.
    """
    executable = shutil.which('nvidia-smi')
    if not executable and os.name == 'nt':
        candidates = [
            Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'nvidia-smi.exe',
            Path(os.environ.get('ProgramFiles', r'C:\Program Files')) /
                'NVIDIA Corporation' / 'NVSMI' / 'nvidia-smi.exe',
        ]
        executable = next((str(path) for path in candidates if path.is_file()), None)
    if not executable:
        return None
    try:
        kwargs = {'capture_output': True, 'text': True, 'encoding': 'utf-8',
                  'errors': 'replace', 'timeout': max(0.2, float(timeout)),
                  'check': False}
        if os.name == 'nt':
            kwargs['creationflags'] = 0x08000000
        result = subprocess.run(
            [executable, '--query-gpu=memory.total,memory.free',
             '--format=csv,noheader,nounits'], **kwargs)
        return parse_nvidia_smi(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


__all__ = ['GpuMemory', 'parse_nvidia_smi', 'detect_gpu_memory']
