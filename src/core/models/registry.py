"""In-memory snapshot projection; no competing persistent model catalogue."""
from .model import ModelInfo


class ModelRegistry:
    def __init__(self, records):
        self._models = {}
        for record in records:
            model = ModelInfo(record['name'], record['manifest'], tuple(record['blobs']),
                              record['size_bytes'], record['shared_bytes'], record['exclusive_bytes'])
            if model.name in self._models:
                raise ValueError('duplicate model name: ' + model.name)
            self._models[model.name] = model

    def get(self, name: str) -> ModelInfo | None:
        return self._models.get(name)

    def list(self) -> tuple[ModelInfo, ...]:
        return tuple(self._models[name] for name in sorted(self._models))
