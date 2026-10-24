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


@pytest.mark.parametrize("text", [
    "#отчет #CuriousCat 11.09 5432 #ачивка Золотая осень",
    "#ачивка Золотая осень #отчет #CuriousCat 11.09 5432",
    "#Ачивка #отчет #CuriousCat 11.09 5432",
])
def test_achievement_tag_ignored(text):
    r = parse_report(text)
    assert r.nickname == "CuriousCat"
    assert r.ambiguous_nicknames == []
    assert r.steps == 5432


def test_achievement_without_nickname_leaves_nickname_empty():
    r = parse_report("#отчет 11.09 5432 #ачивка Золотая осень")
    assert r.nickname is None
    assert r.ambiguous_nicknames == []
    assert r.steps == 5432


def test_several_nicknames_ambiguous():
    r = parse_report("#отчет #alice #bob 1.5.2024 8000")
    assert r.nickname is None
    assert r.ambiguous_nicknames == ["alice", "bob"]


def test_same_nickname_twice_not_ambiguous():
    r = parse_report("#отчет #alice 1.5.2024 8000 #Alice")
    assert r.nickname == "alice"
    assert r.ambiguous_nicknames == []


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


# ---------------------------------------------------------------------------
# Date range reports
# ---------------------------------------------------------------------------

def test_range_basic():
    r = parse_report("#отчет #CuriousCat 21.06-24.06 100,200,5,1943")
    year = datetime.now().year
    assert r.is_range
    assert r.nickname == "CuriousCat"
    assert r.date == datetime(year, 6, 21)
    assert r.date_to == datetime(year, 6, 24)
    assert r.steps_list == [100, 200, 5, 1943]


@pytest.mark.parametrize("text", [
    "#отчет #u 21.06 - 24.06 100, 200, 5, 1943",
    "#отчет #u 21.06–24.06 100,200,5,1943",
    "100,200,5,1943 #u 21.06-24.06 #отчет",
])
def test_range_spacing_dashes_and_order(text):
    r = parse_report(text)
    assert r.is_range
    assert r.date == datetime(datetime.now().year, 6, 21)
    assert r.date_to == datetime(datetime.now().year, 6, 24)
    assert r.steps_list == [100, 200, 5, 1943]


def test_range_start_year_taken_from_end():
    r = parse_report("#отчет #u 30.12-02.01.2025 1,2,3,4")
    assert r.date == datetime(2025, 12, 30)
    assert r.date_to == datetime(2025, 1, 2)


def test_range_explicit_years():
    r = parse_report("#отчет #u 30.12.24-02.01.25 1,2,3,4")
    assert r.date == datetime(2024, 12, 30)
    assert r.date_to == datetime(2025, 1, 2)


def test_range_invalid_date():
    r = parse_report("#отчет #u 30.06-31.06 1,2")
    assert r.is_range
    assert r.date is not None
    assert r.date_to is None


def test_range_steps_missing():
    r = parse_report("#отчет #u 21.06-24.06")
    assert r.is_range
    assert r.steps_list is None


def test_single_report_is_not_range():
    r = parse_report("#отчет #u 21.06 8000")
    assert not r.is_range
    assert r.steps_list is None
