"""UI/provider-independent model inventory summary. Not a live health proof."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    name: str
    manifest: str
    blobs: tuple[str, ...]
    size_bytes: int
    shared_bytes: int
    exclusive_bytes: int

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError('model name must be non-empty')
        if not isinstance(self.manifest, str):
            raise ValueError('model manifest must be a relative path string')
        if not all(isinstance(blob, str) for blob in self.blobs):
            raise ValueError('blob names must be strings')
        object.__setattr__(self, 'blobs', tuple(self.blobs))
        sizes = (self.size_bytes, self.shared_bytes, self.exclusive_bytes)
        if any(type(value) is not int or value < 0 for value in sizes):
            raise ValueError('model sizes must be non-negative integer byte counts')
        if self.size_bytes != self.shared_bytes + self.exclusive_bytes:
            raise ValueError('shared and exclusive bytes must sum to model bytes')
