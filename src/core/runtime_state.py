"""Cross-app last-observed state. A saved 'ready' record is not a health probe."""
from datetime import datetime, timezone
from pathlib import Path
from core.persistence import JsonStore, schema_one

class RuntimeState:
    def __init__(self, path: Path | None = None):
        if path is None:
            from project_paths import USER_DATA_DIR
            path = USER_DATA_DIR / 'cache' / 'runtime-state.json'
        self.store = JsonStore(path)

    def set_status(self, name: str, status: str, *, detail: str = '') -> None:
        if not name or status not in {'unknown', 'starting', 'ready', 'stopping', 'stopped', 'error', 'unavailable'}:
            raise ValueError('invalid runtime status')
        def change(data):
            data = schema_one(data)
            data.setdefault('runtimes', {})[name] = {
                'status': status, 'detail': detail,
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'semantics': 'last_observed',
            }
            return data
        self.store.update(change)

    def snapshot(self) -> dict:
        return schema_one(self.store.read()).get('runtimes', {})
