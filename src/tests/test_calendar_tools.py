"""캘린더의 핵심 규칙. 모델, 외부 API, Windows 알림 창 없이 검증합니다."""
from datetime import datetime, timedelta

import pytest

from services.tools.calendar import CalendarService, latest_occurrence, next_occurrence


def test_basic_calendar_crud_and_task_completion(tmp_path):
    service = CalendarService(tmp_path / 'tools' / 'calendar' / 'items.json')
    item = service.add(title='미팅', start_at='2026-11-30 10:00', remind_minutes=10)
    task = service.add(title='보고서', start_at='2026-11-30 12:00', kind='task')
    assert len(service.list_items()) == 2
    service.set_done(task['id'], True)
    assert next(x for x in service.list_items() if x['id'] == task['id'])['done'] is True
    service.update(item['id'], title='기획 미팅', start_at='2026-12-01 10:00', remind_minutes=5)
    assert service.list_items()[0]['title'] == '기획 미팅'
    service.delete(task['id'])
    assert len(service.list_items()) == 1


def test_due_once_even_when_claimed_twice(tmp_path):
    service = CalendarService(tmp_path / 'items.json')
    service.add(title='일정', start_at='2026-11-22 13:00', remind_minutes=10)
    now = datetime(2026, 11, 22, 12, 50)
    assert len(service.claim_due(now=now)) == 1
    assert service.claim_due(now=now) == []


def test_due_not_before_reminder_and_skip_old(tmp_path):
    service = CalendarService(tmp_path / 'items.json')
    service.add(title='알람', start_at='2026-11-22 13:00', remind_minutes=5)
    assert service.claim_due(now=datetime(2026, 11, 22, 12, 54)) == []
    assert service.claim_due(now=datetime(2026, 11, 25, 12, 00)) == []


def test_daily_weekly_and_monthly_boundaries():
    start = datetime(2026, 1, 31, 9, 0)
    assert latest_occurrence(start, 'monthly', datetime(2026, 2, 28, 10, 0)) == datetime(2026, 2, 28, 9, 0)
    assert next_occurrence(start, 'monthly', datetime(2026, 2, 28, 10, 0)) == datetime(2026, 3, 31, 9, 0)
    assert latest_occurrence(start, 'daily', start + timedelta(days=2, hours=2)) == start + timedelta(days=2)
    assert latest_occurrence(start, 'weekly', start + timedelta(days=15)) == start + timedelta(days=14)


def test_weekly_due_fires_only_for_new_occurrence(tmp_path):
    service = CalendarService(tmp_path / 'items.json')
    service.add(title='운동', start_at='2026-11-23 19:00', repeat='weekly', remind_minutes=0)
    assert len(service.claim_due(now=datetime(2026, 11, 23, 19))) == 1
    assert service.claim_due(now=datetime(2026, 11, 23, 19)) == []
    assert len(service.claim_due(now=datetime(2026, 11, 30, 19))) == 1


def test_task_cannot_repeat_and_bad_input_rejected(tmp_path):
    service = CalendarService(tmp_path / 'items.json')
    with pytest.raises(ValueError):
        service.add(title='매일 작업', kind='task', start_at='2026-11-22 12:00', repeat='daily')
    with pytest.raises(ValueError):
        service.add(title='A', start_at='내일 아침')


def test_due_reset_after_edited_time(tmp_path):
    service = CalendarService(tmp_path / 'items.json')
    item = service.add(title='A', start_at='2026-11-22 13:00', remind_minutes=0)
    service.claim_due(now=datetime(2026, 11, 22, 13))
    service.update(item['id'], title='A', start_at='2026-11-22 15:00', remind_minutes=0)
    assert len(service.claim_due(now=datetime(2026, 11, 22, 15))) == 1


def test_read_does_not_create_files(tmp_path):
    path = tmp_path / 'items.json'
    service = CalendarService(path)
    assert service.list_items() == []
    assert not path.exists()