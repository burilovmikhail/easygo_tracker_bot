import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ReportData:
    nickname: Optional[str] = None
    date: Optional[datetime] = None
    steps: Optional[int] = None


def parse_report(text: str) -> ReportData:
    """
    Parse a #отчет message. Components may appear in any order:
        #отчет #nickname dd.mm.yyyy number_of_steps

    Rules:
    - Nickname: first hashtag that is NOT #отчет (case-insensitive)
    - Date:     first occurrence of dd.mm.yyyy pattern
    - Steps:    first standalone integer after removing the date and all hashtags
    """
    result = ReportData()

    # --- nickname ---
    for tag in re.findall(r"#(\w+)", text, re.IGNORECASE):
        if tag.lower() != "отчет":
            result.nickname = tag
            break

    # --- date ---
    date_match = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", text)
    if date_match:
        try:
            result.date = datetime.strptime(date_match.group(1), "%d.%m.%Y")
        except ValueError:
            pass

    # --- steps: remove date + hashtags first so their digits don't interfere ---
    cleaned = re.sub(r"\d{2}\.\d{2}\.\d{4}", " ", text)
    cleaned = re.sub(r"#\w+", " ", cleaned, flags=re.IGNORECASE)
    numbers = re.findall(r"\b(\d+)\b", cleaned)
    if numbers:
        result.steps = int(numbers[0])

    return result
