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
        value = appearance.get('theme', 'light')
        if not isinstance(value, str) or value not in ('dark', 'light'):
            raise ValueError('unsupported theme preference')
        return value

    def activity_visible(self) -> bool:
        """Is the shared activity log expanded? Defaults to no for a calm workspace."""
        data = schema_one(self.store.read())
        appearance = data.get('appearance', {})
        if not isinstance(appearance, dict):
            raise ValueError('appearance settings must be an object')
        value = appearance.get('activity_log', False)
        if not isinstance(value, bool):
            raise ValueError('activity_log must be true or false')
        return value

    def set_activity_visible(self, visible: bool) -> None:
        if not isinstance(visible, bool):
            raise ValueError('activity_log must be true or false')
        def change(data):
            data = schema_one(data)
            appearance = data.setdefault('appearance', {})
            if not isinstance(appearance, dict):
                raise ValueError('appearance settings must be an object')
            appearance['activity_log'] = visible
            return data
        self.store.update(change)

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

    # 번역 도구에서 지난번에 고른 값(언어·모델·고급 설정). 다음에 열 때 그대로 채워 선택을 줄인다.
    TRANSLATION_KEYS = {'target': str, 'model': str, 'source': str, 'kind': str, 'style': str,
                        'shared': bool, 'resume': bool, 'keep_failed': bool, 'precise': bool,
                        'stage': bool, 'translate_name': bool, 'advanced': bool, 'last_dir': str,
                        'glossary': str, 'folded': str}
    # 문자열 길이 상한(기본 300자). 폴더 경로와 용어집은 더 길 수 있다.
    TRANSLATION_LIMITS = {'last_dir': 2000, 'glossary': 20000}

    # 자막 도구에서 지난번에 고른 값(인식 모델·언어·형식·품질·번역 연결).
    SUBTITLE_KEYS = {'model': str, 'language': str, 'format': str, 'quality': str, 'vad': bool,
                     'keep_sounds': bool, 'gpu': bool, 'sensitive_vad': bool, 'max_chars': int, 'max_lines': int,
                     'prompt': str, 'translate': bool, 'target': str, 'llm': str, 'style': str, 'main_name': bool,
                     'advanced': bool, 'last_dir': str, 'folded': str, 'translate_name': bool}
    SUBTITLE_LIMITS = {'last_dir': 2000, 'prompt': 2000}

    @staticmethod
    def _allowed(values, keys, limits):
        return {key: item for key, item in dict(values).items()
                if key in keys and isinstance(item, keys[key])
                and not (keys[key] is int and isinstance(item, bool))
                and (not isinstance(item, str) or len(item) <= limits.get(key, 300))}

    def _section(self, name, keys, limits) -> dict:
        data = schema_one(self.store.read())
        value = data.get(name, {})
        if not isinstance(value, dict):
            return {}
        return self._allowed(value, keys, limits)

    def _set_section(self, name, values, keys, limits) -> None:
        clean = self._allowed(values, keys, limits)
        def change(data):
            data = schema_one(data)
            data[name] = clean
            return data
        self.store.update(change)

    def translation_preferences(self) -> dict:
        return self._section('translation', self.TRANSLATION_KEYS, self.TRANSLATION_LIMITS)

    def set_translation_preferences(self, values: dict) -> None:
        self._set_section('translation', values, self.TRANSLATION_KEYS, self.TRANSLATION_LIMITS)

    def subtitle_preferences(self) -> dict:
        return self._section('subtitles', self.SUBTITLE_KEYS, self.SUBTITLE_LIMITS)

    def set_subtitle_preferences(self, values: dict) -> None:
        self._set_section('subtitles', values, self.SUBTITLE_KEYS, self.SUBTITLE_LIMITS)
