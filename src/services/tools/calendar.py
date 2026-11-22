"""개인 일정/할 일 저장소. LLM, MCP 및 GUI에 의존하지 않습니다.

JsonStore의 계정별 DPAPI 보호, 원자적 쓰기, 프로세스 간 잠금을 재사용합니다.
시각은 PC의 로컬 벽시계 시간으로 저장합니다(시간대 이동 자동 변환 없음).
"""
from __future__ import annotations

import calendar as month_calendar
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from core.persistence import JsonStore

KINDS = ('event', 'task')
REPEATS = ('none', 'daily', 'weekly', 'monthly')
MAX_ITEMS = 2000


def _moment(value: str) -> datetime:
    """ISO 로컬 시각 파싱: 정확한 분 단위/시간대 없는 입력만 허용."""
    if not isinstance(value, str):
        raise ValueError('날짜와 시간을 입력하세요.')
    try:
        moment = datetime.strptime(value.strip().replace('T', ' '), '%Y-%m-%d %H:%M')
    except ValueError as exc:
        raise ValueError('날짜와 시간은 YYYY-MM-DD HH:MM 형식으로 입력하세요.') from exc
    return moment


def _month_offset(start: datetime, steps: int) -> datetime:
    index = start.year * 12 + start.month - 1 + steps
    year, month_zero = divmod(index, 12)
    month = month_zero + 1
    day = min(start.day, month_calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def latest_occurrence(start: datetime, repeat: str, cutoff: datetime) -> datetime | None:
    """cutoff 이전에 발생한 마지막 회차(반복은 처음 시작한 날짜에 고정)."""
    if start > cutoff:
        return None
    if repeat == 'none':
        return start
    if repeat in ('daily', 'weekly'):
        interval = timedelta(days=1 if repeat == 'daily' else 7)
        return start + ((cutoff - start) // interval) * interval
    if repeat == 'monthly':
        steps = (cutoff.year - start.year) * 12 + cutoff.month - start.month
        value = _month_offset(start, steps)
        return value if value <= cutoff else _month_offset(start, steps - 1)
    raise ValueError('지원하지 않는 반복 규칙입니다.')


def next_occurrence(start: datetime, repeat: str, now: datetime) -> datetime | None:
    """현재 이후에 시작하는 첫 일정. 이미 시작한 단일 일정은 None."""
    if start >= now:
        return start
    last = latest_occurrence(start, repeat, now)
    if repeat == 'none':
        return None
    if last == now:
        return last
    if repeat == 'daily':
        return last + timedelta(days=1)
    if repeat == 'weekly':
        return last + timedelta(days=7)
    steps = (last.year - start.year) * 12 + last.month - start.month + 1
    return _month_offset(start, steps)


def _clean_fields(title, start_at, kind, repeat, remind_minutes, note):
    title = str(title).strip()
    note = str(note).strip()
    if not title or len(title) > 120 or '\n' in title or '\r' in title:
        raise ValueError('제목은 1~120자의 한 줄이어야 합니다.')
    if len(note) > 2000:
        raise ValueError('메모는 2000자 이하로 입력하세요.')
    if kind not in KINDS:
        raise ValueError('일정 또는 할 일을 선택하세요.')
    if repeat not in REPEATS or (kind == 'task' and repeat != 'none'):
        raise ValueError('반복 할 일은 아직 지원하지 않습니다.')
    if remind_minutes is not None and (type(remind_minutes) is not int or not 0 <= remind_minutes <= 10080):
        raise ValueError('알림 시간은 0~10080분 이내여야 합니다.')
    start = _moment(start_at)
    return dict(title=title, start_at=start.isoformat(timespec='minutes'),
                kind=kind, repeat=repeat, remind_minutes=remind_minutes, note=note)


class CalendarService:
    def __init__(self, path: Path):
        self.store = JsonStore(Path(path))

    @property
    def path(self):
        return self.store.path

    @staticmethod
    def _items(data):
        records = data.get('items', [])
        if not isinstance(records, list):
            raise ValueError('일정 파일 형식이 손상되었습니다.')
        return records

    def list_items(self) -> list[dict]:
        return [dict(item) for item in self._items(self.store.read())]

    def add(self, *, title, start_at, kind='event', repeat='none', remind_minutes=None, note='') -> dict:
        record = _clean_fields(title, start_at, kind, repeat, remind_minutes, note)
        record.update(id=uuid4().hex, done=False, last_alert='')
        def write(data):
            items = self._items(data)
            if len(items) >= MAX_ITEMS:
                raise ValueError('일정은 최대 2000개까지 저장할 수 있습니다.')
            items.append(record)
            data['items'] = items
            return data
        self.store.update(write)
        return dict(record)

    def update(self, item_id: str, *, title, start_at, kind='event', repeat='none', remind_minutes=None, note='') -> dict:
        fields = _clean_fields(title, start_at, kind, repeat, remind_minutes, note)
        found = []
        def write(data):
            for item in self._items(data):
                if item.get('id') == item_id:
                    if any(item.get(key) != fields[key] for key in ('start_at', 'repeat', 'remind_minutes', 'kind')):
                        item['last_alert'] = ''
                    if item.get('kind') != fields['kind']:
                        item['done'] = False
                    item.update(fields)
                    found.append(dict(item))
                    return data
            raise KeyError('선택한 일정이 존재하지 않습니다.')
        self.store.update(write)
        return found[0]

    def delete(self, item_id: str) -> None:
        def write(data):
            items = self._items(data)
            kept = [item for item in items if item.get('id') != item_id]
            if len(kept) == len(items):
                raise KeyError('선택한 일정이 존재하지 않습니다.')
            data['items'] = kept
            return data
        self.store.update(write)

    def set_done(self, item_id: str, done: bool) -> None:
        if type(done) is not bool:
            raise ValueError('완료 여부는 참/거짓이어야 합니다.')
        def write(data):
            for item in self._items(data):
                if item.get('id') == item_id and item.get('kind') == 'task':
                    item['done'] = done
                    return data
            raise KeyError('선택한 할 일이 존재하지 않습니다.')
        self.store.update(write)

    @staticmethod
    def _due(item: dict, now: datetime, grace: timedelta) -> tuple[datetime, datetime] | None:
        if item.get('done') or item.get('remind_minutes') is None:
            return None
        start = _moment(item['start_at'])
        lead = int(item['remind_minutes'])
        occurrence = latest_occurrence(start, item.get('repeat', 'none'), now + timedelta(minutes=lead))
        if occurrence is None or item.get('last_alert') == occurrence.isoformat(timespec='minutes'):
            return None
        alert_at = occurrence - timedelta(minutes=lead)
        if timedelta(0) <= now - alert_at <= grace:
            return occurrence, alert_at
        return None

    def claim_due(self, *, now: datetime | None = None, grace_hours: int = 12, limit: int = 5) -> list[dict]:
        """알림을 원자적으로 예약 완료 처리. 중복 worker도 같은 회차를 두 번 받지 않습니다."""
        now = now or datetime.now()
        if now.tzinfo is not None:
            now = now.astimezone().replace(tzinfo=None)
        grace = timedelta(hours=grace_hours)
        # 알림 없는 평소 polling은 기록 파일을 다시 쓰지 않습니다.
        if not any(self._due(item, now, grace) for item in self.list_items()):
            return []
        selected = []
        def write(data):
            for item in self._items(data):
                if len(selected) >= limit:
                    break
                match = self._due(item, now, grace)
                if match is None:
                    continue
                occurrence, alert_at = match
                item['last_alert'] = occurrence.isoformat(timespec='minutes')
                selected.append({**item, 'occurrence_at': occurrence.isoformat(timespec='minutes'),
                                 'alert_at': alert_at.isoformat(timespec='minutes')})
            return data
        self.store.update(write)
        return selected