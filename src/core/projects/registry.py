from pathlib import Path
from core.persistence import JsonStore, schema_one
from .model import Project

class ProjectRegistry:
    def __init__(self, path: Path | None = None):
        if path is None:
            from project_paths import USER_DATA_DIR
            path = USER_DATA_DIR / 'projects' / 'registry.json'
        self.store = JsonStore(path)

    def save(self, project: Project) -> None:
        if not isinstance(project, Project):
            raise TypeError('project must be a Project')
        def change(data):
            data = schema_one(data)
            data.setdefault('projects', {})[project.id] = project.to_dict()
            return data
        self.store.update(change)

    def get(self, identifier: str) -> Project | None:
        data = schema_one(self.store.read()).get('projects', {}).get(identifier)
        return Project(**data) if data is not None else None

    def list(self) -> list[Project]:
        values = schema_one(self.store.read()).get('projects', {})
        return [Project(**values[key]) for key in sorted(values)]

    def delete(self, identifier: str) -> None:
        def change(data):
            data = schema_one(data)
            data.setdefault('projects', {}).pop(identifier, None)
            return data
        self.store.update(change)
