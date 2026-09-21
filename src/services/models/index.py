"""Transition adapter to the existing canonical index, not a second scanner.

The legacy public FileRow/refresh APIs remain available during the staged move.
No apps or presenters are imported. The old index is relocated only after its
full dependency suite is available; this adapter preserves its exact behavior.
"""
from launcher.models.model_files import build_index, read_manifests, refresh

__all__ = ["build_index", "read_manifests", "refresh"]
