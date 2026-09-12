"""Shared settings at the existing user_data root. No legacy data relocation."""
from pathlib import Path
from core.persistence import JsonStore, schema_one
from core.network.policy import NetworkMode, resolve_mode

class SettingsStore:
    def __init__(self, path: Path | None = None):
        if path is None:
            from project_paths import USER_DATA_DIR
            path = USER_DATA_DIR / 'settings' / 'localai.json'
        self.store = JsonStore(path)

    def set_network_mode(self, mode: str, *, app: str | None = None) -> None:
        value = NetworkMode(mode).value
        if app is not None and app not in ('studio', 'chat', 'interpreter', 'setup'):
            raise ValueError('unknown application')
        def change(data):
            data = schema_one(data)
            if app is None:
                data.setdefault('global', {})['network_mode'] = value
            else:
                data.setdefault('apps', {}).setdefault(app, {})['network_mode'] = value
            return data
        self.store.update(change)

    def network_mode(self, *, app: str | None = None, project=None, session=None, fallback='warp'):
        data = schema_one(self.store.read())
        return resolve_mode(session=session, project=project,
                            app=data.get('apps', {}).get(app, {}).get('network_mode'),
                            global_mode=data.get('global', {}).get('network_mode', fallback))

    def theme(self) -> str:
        """One appearance preference shared by Studio and standalone windows."""
        data = schema_one(self.store.read())
        appearance = data.get('appearance', {})
        if not isinstance(appearance, dict):
            raise ValueError('appearance settings must be an object')
        value = appearance.get('theme', 'dark')
        if not isinstance(value, str) or value not in ('dark', 'light'):
            raise ValueError('unsupported theme preference')
        return value

    def set_theme(self, theme: str) -> None:
        if not isinstance(theme, str) or theme not in ('dark', 'light'):
            raise ValueError('theme must be dark or light')
        def change(data):
            data = schema_one(data)
            appearance = data.setdefault('appearance', {})
            if not isinstance(appearance, dict):
                raise ValueError('appearance settings must be an object')
            appearance['theme'] = theme
            return data
        self.store.update(change)
