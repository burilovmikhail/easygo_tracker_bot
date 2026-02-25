import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Matches d.m, d.m.yy, d.m.yyyy (and dd/mm variants).
# Year group is optional; 2-digit years are treated as 20xx.
_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b")


@dataclass
class ReportData:
    nickname: Optional[str] = None
    date: Optional[datetime] = None
    steps: Optional[int] = None


def parse_report(text: str) -> ReportData:
    """
    Parse a #отчет message. Components may appear in any order:
        #отчет #nickname <date> number_of_steps

    Rules:
    - Nickname: first hashtag that is NOT #отчет (case-insensitive)
    - Date:     first occurrence of d.m, d.m.yy, d.m.yyyy (dd/mm variants too)
                Missing year → current year; 2-digit year → 20xx
    - Steps:    first standalone integer after removing the date and all hashtags
    """
    result = ReportData()

    # --- nickname ---
    for tag in re.findall(r"#(\w+)", text, re.IGNORECASE):
        if tag.lower() != "отчет":
            result.nickname = tag
            break

    # --- date ---
    date_match = _DATE_RE.search(text)
    if date_match:
        day, month, year_str = int(date_match.group(1)), int(date_match.group(2)), date_match.group(3)
        if year_str is None:
            year = datetime.now().year
        elif len(year_str) == 2:
            year = 2000 + int(year_str)
        else:
            year = int(year_str)
        try:
            result.date = datetime(year, month, day)
        except ValueError:
            pass

    # --- steps: remove date + hashtags first so their digits don't interfere ---
    cleaned = _DATE_RE.sub(" ", text)
    cleaned = re.sub(r"#\w+", " ", cleaned, flags=re.IGNORECASE)
    numbers = re.findall(r"\b(\d+)\b", cleaned)
    if numbers:
        result.steps = int(numbers[0])

    return result
