from datetime import datetime, timedelta

import pytest

from bot.handlers import _VLADIVOSTOK_TZ, _range_entries
from bot.parser import parse_report

TODAY = datetime.now(_VLADIVOSTOK_TZ).replace(tzinfo=None, hour=0, minute=0,
                                               second=0, microsecond=0)


def _range_text(start: datetime, end: datetime, steps: str) -> str:
    return f"#отчет #u {start:%d.%m.%Y}-{end:%d.%m.%Y} {steps}"


def test_range_entries_ok():
    start = TODAY - timedelta(days=3)
    if start.year != TODAY.year:
        pytest.skip("range would cross the year boundary")
    entries, error = _range_entries(parse_report(_range_text(start, TODAY, "100,200,5,1943")))
    assert error is None
    assert entries == [
        (start, 100),
        (start + timedelta(days=1), 200),
        (start + timedelta(days=2), 5),
        (TODAY, 1943),
    ]


def test_range_single_day():
    entries, error = _range_entries(parse_report(_range_text(TODAY, TODAY, "500")))
    assert error is None
    assert entries == [(TODAY, 500)]


@pytest.mark.parametrize("steps", ["100,200,5", "100,200,5,1943,7"])
def test_range_count_mismatch(steps):
    start = TODAY - timedelta(days=3)
    if start.year != TODAY.year:
        pytest.skip("range would cross the year boundary")
    entries, error = _range_entries(parse_report(_range_text(start, TODAY, steps)))
    assert entries == []
    assert "не совпадает" in error
    assert "(4)" in error


def test_range_start_after_end():
    start = TODAY - timedelta(days=3)
    entries, error = _range_entries(parse_report(_range_text(TODAY, start, "1,2,3,4")))
    assert entries == []
    assert "начало позже конца" in error


def test_range_future_end():
    entries, error = _range_entries(
        parse_report(_range_text(TODAY, TODAY + timedelta(days=1), "1,2")))
    assert entries == []
    assert "не наступила" in error


def test_range_previous_year():
    y = TODAY.year - 1
    entries, error = _range_entries(parse_report(f"#отчет #u 01.06.{y}-02.06.{y} 1,2"))
    assert entries == []
    assert "текущий год" in error


def test_range_invalid_date():
    entries, error = _range_entries(parse_report("#отчет #u 30.06-31.06 1,2"))
    assert entries == []
    assert error == "Недопустимый диапазон дат"


def test_range_no_steps():
    entries, error = _range_entries(parse_report(_range_text(TODAY, TODAY, "")))
    assert entries == []
    assert error == "Отсутствует количество шагов"


def test_range_too_long():
    start = datetime(TODAY.year, 1, 1)
    end = start + timedelta(days=31)
    if end > TODAY:
        pytest.skip("not enough elapsed days this year")
    steps = ",".join(["1"] * 32)
    entries, error = _range_entries(parse_report(_range_text(start, end, steps)))
    assert entries == []
    assert "Слишком длинный диапазон" in error
