import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Matches d.m, d.m.yy, d.m.yyyy (and dd/mm variants).
# Year group is optional; 2-digit years are treated as 20xx.
_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b")

# Service hashtags that are never treated as a nickname (lower-case).
_SERVICE_TAGS = {"отчет", "отчёт", "ачивка", "ачивки", "ачивку"}

# Matches a date range: d.m[.y]-d.m[.y] (hyphen, en dash or em dash).
_RANGE_RE = re.compile(
    r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s*[-–—]\s*"
    r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b"
)

# Comma-separated step counts: 100,200,5 or 100, 200, 5
_STEPS_LIST_RE = re.compile(r"\b\d+(?:\s*,\s*\d+)*\b")


@dataclass
class ReportData:
    nickname: Optional[str] = None
    date: Optional[datetime] = None
    steps: Optional[int] = None
    # Set when more than one non-service hashtag is present — the nickname is
    # ambiguous and ``nickname`` stays None.
    ambiguous_nicknames: list[str] = field(default_factory=list)
    # Range reports: "#отчет #nick 21.06-24.06 100,200,5,1943"
    is_range: bool = False
    date_to: Optional[datetime] = None
    steps_list: Optional[list[int]] = None


def _parse_year(year_str: Optional[str], default: int) -> int:
    if year_str is None:
        return default
    if len(year_str) == 2:
        return 2000 + int(year_str)
    return int(year_str)


def _make_date(year: int, month: int, day: int) -> Optional[datetime]:
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def parse_report(text: str) -> ReportData:
    """
    Parse a #отчет message. Components may appear in any order:
        #отчет #nickname <date> number_of_steps

    Rules:
    - Nickname: the only hashtag that is not a service tag (#отчет, #ачивка…),
                case-insensitive. Several distinct candidates → ``nickname`` is
                None and ``ambiguous_nicknames`` lists them.
    - Date:     first occurrence of d.m, d.m.yy, d.m.yyyy (dd/mm variants too)
                Missing year → current year; 2-digit year → 20xx
    - Steps:    first standalone integer after removing the date and all hashtags

    Range form: ``#отчет #nickname d.m-d.m s1,s2,...`` (both dates inclusive).
    Sets ``is_range``, ``date`` (start), ``date_to`` (end) and ``steps_list``.
    A missing start year is taken from the end date, then the current year.
    The day count vs. number of values is NOT checked here — the caller does it.
    """
    result = ReportData()

    # --- nickname ---
    candidates: list[str] = []
    for tag in re.findall(r"#(\w+)", text, re.IGNORECASE):
        if tag.lower() in _SERVICE_TAGS:
            continue
        if tag.lower() not in (c.lower() for c in candidates):
            candidates.append(tag)
    if len(candidates) == 1:
        result.nickname = candidates[0]
    elif len(candidates) > 1:
        result.ambiguous_nicknames = candidates

    # --- date range ---
    range_match = _RANGE_RE.search(text)
    if range_match:
        result.is_range = True
        d1, m1, y1, d2, m2, y2 = range_match.groups()
        end_year = _parse_year(y2, datetime.now().year)
        start_year = _parse_year(y1, end_year)
        result.date = _make_date(start_year, int(m1), int(d1))
        result.date_to = _make_date(end_year, int(m2), int(d2))

        cleaned = _RANGE_RE.sub(" ", text)
        cleaned = re.sub(r"#\w+", " ", cleaned, flags=re.IGNORECASE)
        steps_match = _STEPS_LIST_RE.search(cleaned)
        if steps_match:
            result.steps_list = [int(x) for x in re.split(r"\s*,\s*", steps_match.group())]
        return result

    # --- date ---
    date_match = _DATE_RE.search(text)
    if date_match:
        day, month, year_str = int(date_match.group(1)), int(date_match.group(2)), date_match.group(3)
        result.date = _make_date(_parse_year(year_str, datetime.now().year), month, day)

    # --- steps: remove date + hashtags first so their digits don't interfere ---
    cleaned = _DATE_RE.sub(" ", text)
    cleaned = re.sub(r"#\w+", " ", cleaned, flags=re.IGNORECASE)
    numbers = re.findall(r"\b(\d+)\b", cleaned)
    if numbers:
        result.steps = int(numbers[0])

    return result
