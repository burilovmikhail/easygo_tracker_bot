import calendar
import time
from datetime import datetime
from typing import Optional

import gspread
import structlog
from google.oauth2.service_account import Credentials

from bot.decorators import retry

logger = structlog.get_logger()

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_MONTH_NAMES_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}
_MONTH_HEADER_SET = set(_MONTH_NAMES_RU.values())


class SheetsService:
    """Read/write helper for the step-tracking Google Spreadsheet.

    Sheet layout — month sections stacked vertically:
        A           | B      | C      | ...
        МАРТ        |        |        |   ← month header (merged, uppercase, case-insensitive match)
        Ник         | 01.03  | 02.03  | … | 31.03
        #vasya      | 8500   |        | …
        #petya      | 12000  |        | …   ← gold background for 1st place
        АПРЕЛЬ      |        |        |   ← next month header
        Ник         | 01.04  | …

    Each month section is pre-filled with all days of that month on creation.
    Medal places colour the cell background (gold/silver/bronze).
    Missing month sections and nickname rows are appended automatically.
    """

    def __init__(
        self,
        credentials_path: str,
        spreadsheet_id: str,
        steps_worksheet: str = "Шаги",
    ) -> None:
        creds = Credentials.from_service_account_file(
            credentials_path, scopes=_SCOPES
        )
        self._client = gspread.authorize(creds)
        self._spreadsheet_id = spreadsheet_id
        self._steps_worksheet = steps_worksheet

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry(attempts=4, initial_delay=5, backoff_factor=3, max_delay=30, jitter=False)
    def write_steps(self, nickname: str, date: datetime, steps: int) -> None:
        """Write *steps* into the steps sheet at (nickname, date)."""
        sheet = self._get_sheet()
        nickname = self._normalise_nick(nickname)

        all_values = sheet.get_all_values()
        col_idx, row_idx = self._ensure_cell(sheet, all_values, nickname, date)

        sheet.update_cell(row_idx + 1, col_idx + 1, steps)
        logger.info("Wrote steps to sheet", nickname=nickname,
                    date=date.strftime("%d.%m.%Y"), steps=steps)

    # RGB (0–1 floats) for each medal place
    _MEDAL_COLORS = {
        "🥇": {"red": 1.0,   "green": 0.843, "blue": 0.0},    # gold
        "🥈": {"red": 0.753, "green": 0.753, "blue": 0.753},  # silver
        "🥉": {"red": 0.804, "green": 0.498, "blue": 0.196},  # bronze
    }

    # AG (col 33) is totals; medals start at AH (col 34, 1-based).
    _MEDALS_START_COL = 34  # 1-based

    @retry(attempts=4, initial_delay=5, backoff_factor=3, max_delay=30, jitter=False)
    def write_medal(self, nickname: str, date: datetime, symbol: str) -> None:
        """Write medal symbol into the first empty cell in the medals area (AH+).

        🥇 → gold, 🥈 → silver, 🥉 → bronze.
        The medal symbol is written into the cell and the background is coloured.
        """
        color = self._MEDAL_COLORS.get(symbol)
        if color is None:
            logger.warning("Unknown medal symbol, skipping", symbol=symbol)
            return

        sheet = self._get_sheet()
        nickname = self._normalise_nick(nickname)

        all_values = sheet.get_all_values()
        col_idx, row_idx = self._ensure_cell(sheet, all_values, nickname, date)

        # Re-fetch the row so we see any changes made by _ensure_cell
        all_values = sheet.get_all_values()
        row = all_values[row_idx] if row_idx < len(all_values) else []

        # Format the steps value cell with the medal colour
        steps_cell_a1 = gspread.utils.rowcol_to_a1(row_idx + 1, col_idx + 1)
        sheet.format(steps_cell_a1, {"backgroundColor": color})

        # Find first empty cell starting at _MEDALS_START_COL (convert to 0-based)
        medal_col_idx = self._MEDALS_START_COL - 1
        while medal_col_idx < len(row) and row[medal_col_idx]:
            medal_col_idx += 1

        cell_a1 = gspread.utils.rowcol_to_a1(row_idx + 1, medal_col_idx + 1)
        sheet.update_cell(row_idx + 1, medal_col_idx + 1, symbol)
        sheet.format(cell_a1, {"backgroundColor": color})
        logger.info("Wrote medal cell", nickname=nickname, date=date.strftime(
            "%d.%m.%Y"), symbol=symbol, cell=cell_a1, steps_cell=steps_cell_a1)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_nick(nickname: str) -> str:
        return f"#{nickname}" if not nickname.startswith("#") else nickname

    @staticmethod
    def _is_month_header(text: str) -> bool:
        return text.strip().upper() in {m.upper() for m in _MONTH_HEADER_SET}

    @staticmethod
    def _month_header(date: datetime) -> str:
        return _MONTH_NAMES_RU[date.month].upper()

    def _parse_sections(self, all_values: list[list[str]]) -> list[dict]:
        """Parse the sheet into month sections.

        Returns list of dicts with keys:
          month_header, header_row, dates_row, data_start, data_end  (all 0-based row indices).
        data_end is exclusive (index of next header or len(all_values)).
        """
        sections = []
        i = 0
        while i < len(all_values):
            row = all_values[i]
            if row and row[0] and self._is_month_header(row[0]):
                j = i + 2  # start looking for next header after dates row
                while j < len(all_values):
                    r = all_values[j]
                    if r and r[0] and self._is_month_header(r[0]):
                        break
                    j += 1
                sections.append({
                    "month_header": row[0],
                    "header_row": i,
                    "dates_row": i + 1,
                    "data_start": i + 2,
                    "data_end": j,
                })
                i = j
            else:
                i += 1
        return sections

    def _ensure_cell(
        self,
        sheet: gspread.Worksheet,
        all_values: list[list[str]],
        nickname: str,
        date: datetime,
    ) -> tuple[int, int]:
        """Return (col_idx, row_idx) for (nickname, date), creating them if needed.

        Both indices are 0-based; add 1 when calling sheet.update_cell().
        """
        month_header = self._month_header(date)
        date_col_str = date.strftime("%d.%m")

        # Find the month section
        sections = self._parse_sections(all_values)
        section = next(
            (s for s in sections if s["month_header"].upper() == month_header), None)

        if section is None:
            raise ValueError(
                f"Month section for {month_header} not found"
            )

        # Find date column in the pre-filled dates row
        dates_row = all_values[section["dates_row"]
                               ] if section["dates_row"] < len(all_values) else []
        col_idx: Optional[int] = None
        for i, cell in enumerate(dates_row):
            if i == 0:
                continue  # skip "Ник" column
            if cell == date_col_str:
                col_idx = i
                break

        if col_idx is None:
            raise ValueError(
                f"Date {date_col_str} not found in pre-filled section for {month_header}"
            )

        # Find or create nickname row within the section
        row_idx: Optional[int] = None
        for i in range(section["data_start"], section["data_end"]):
            row = all_values[i] if i < len(all_values) else []
            if row and row[0].lower() == nickname.lower():
                row_idx = i
                break

        if row_idx is None:
            row_idx = section["data_end"]
            if row_idx < len(all_values):
                # Another section follows — insert a row to avoid overwriting it
                sheet.insert_rows([[nickname]], row=row_idx + 1)
            else:
                sheet.update_cell(row_idx + 1, 1, nickname)
            logger.info("Created new nickname row",
                        nickname=nickname, row=row_idx + 1)

        return col_idx, row_idx

    @retry(attempts=4, initial_delay=5, backoff_factor=3, max_delay=30, jitter=False)
    def _batch_update(self, sheet: gspread.Worksheet, updates: list[dict]) -> None:
        sheet.batch_update(updates)

    @retry(attempts=4, initial_delay=5, backoff_factor=3, max_delay=30, jitter=False)
    def _format_cell(self, sheet: gspread.Worksheet, cell_a1: str, fmt: dict) -> None:
        sheet.format(cell_a1, fmt)

    def _get_sheet(self) -> gspread.Worksheet:
        spreadsheet = self._client.open_by_key(self._spreadsheet_id)
        try:
            return spreadsheet.worksheet(self._steps_worksheet)
        except gspread.WorksheetNotFound:
            logger.info("Worksheet not found, creating it",
                        name=self._steps_worksheet)
            return spreadsheet.add_worksheet(title=self._steps_worksheet, rows=200, cols=50)
