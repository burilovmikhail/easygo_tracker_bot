from datetime import datetime

import pytest

from bot.parser import parse_report


# ---------------------------------------------------------------------------
# Nickname
# ---------------------------------------------------------------------------

def test_nickname_extracted():
    r = parse_report("#отчет #alice 1.5.2024 8000")
    assert r.nickname == "alice"


def test_nickname_missing():
    r = parse_report("#отчет 1.5.2024 8000")
    assert r.nickname is None


def test_nickname_report_tag_case_insensitive():
    r = parse_report("#Отчет #Bob 1.5.2024 8000")
    assert r.nickname == "Bob"


def test_nickname_before_report_tag():
    r = parse_report("#alice #отчет 1.5.2024 8000")
    assert r.nickname == "alice"


# ---------------------------------------------------------------------------
# Date formats
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("#отчет #u 31.12.2024 1000",  datetime(2024, 12, 31)),
    ("#отчет #u 01.05.2024 1000",  datetime(2024, 5, 1)),
    ("#отчет #u 31.12.24 1000",    datetime(2024, 12, 31)),
    ("#отчет #u 01.05.24 1000",    datetime(2024, 5, 1)),
    ("#отчет #u 1.5.2024 1000",    datetime(2024, 5, 1)),
    ("#отчет #u 1.5.24 1000",      datetime(2024, 5, 1)),
    ("#отчет #u 9.3.2024 1000",    datetime(2024, 3, 9)),
])
def test_date_formats(text, expected):
    r = parse_report(text)
    assert r.date == expected


def test_date_dd_mm_uses_current_year():
    r = parse_report("#отчет #u 15.08 8000")
    assert r.date == datetime(datetime.now().year, 8, 15)


def test_date_d_m_uses_current_year():
    r = parse_report("#отчет #u 5.3 8000")
    assert r.date == datetime(datetime.now().year, 3, 5)


def test_date_missing():
    r = parse_report("#отчет #alice 8000")
    assert r.date is None


def test_date_invalid_ignored():
    r = parse_report("#отчет #u 32.13.2024 8000")
    assert r.date is None


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def test_steps_extracted():
    r = parse_report("#отчет #alice 1.5.2024 8000")
    assert r.steps == 8000


def test_steps_missing():
    r = parse_report("#отчет #alice 1.5.2024")
    assert r.steps is None


def test_steps_not_confused_by_date_digits():
    r = parse_report("#отчет #alice 5.3.2024 12345")
    assert r.steps == 12345


def test_steps_no_date():
    r = parse_report("#отчет #alice 7500")
    assert r.steps == 7500


def test_steps_large_number():
    r = parse_report("#отчет #alice 1.5.2024 25000")
    assert r.steps == 25000


# ---------------------------------------------------------------------------
# Order independence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "#отчет #alice 1.5.2024 8000",
    "#alice #отчет 1.5.2024 8000",
    "8000 #отчет #alice 1.5.2024",
    "1.5.2024 8000 #отчет #alice",
    "#отчет 8000 1.5.2024 #alice",
])
def test_order_independence(text):
    r = parse_report(text)
    assert r.nickname == "alice", f"failed for: {text!r}"
    assert r.date == datetime(2024, 5, 1), f"failed for: {text!r}"
    assert r.steps == 8000, f"failed for: {text!r}"


# ---------------------------------------------------------------------------
# All fields missing
# ---------------------------------------------------------------------------

def test_empty_report_tag_only():
    r = parse_report("#отчет")
    assert r.nickname is None
    assert r.date is None
    assert r.steps is None
