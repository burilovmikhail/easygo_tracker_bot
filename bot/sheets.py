from datetime import datetime
from typing import Optional

import gspread
import structlog
from google.oauth2.service_account import Credentials

logger = structlog.get_logger()

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsService:
    """Read/write helper for the step-tracking Google Spreadsheet.

    Sheet layout (worksheet_name):
        A1        | B1         | C1         | ...
        Nick      | DD.MM.YYYY | DD.MM.YYYY | ...
        vasya     | 8500       |            | ...
        petya     | 12000 🥇   |            | ...

    Medals are appended to the existing step-count cell, e.g. "11000 🥇".
    Missing rows/columns are appended automatically.
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

    def write_steps(self, nickname: str, date: datetime, steps: int) -> None:
        """Write *steps* into the steps sheet at (nickname, date)."""
        sheet = self._get_sheet()
        nickname = self._normalise_nick(nickname)
        date_str = date.strftime("%d.%m.%Y")

        all_values = sheet.get_all_values()
        col_idx, row_idx = self._ensure_cell(sheet, all_values, nickname, date_str)

        sheet.update_cell(row_idx + 1, col_idx + 1, steps)
        logger.info("Wrote steps to sheet", nickname=nickname, date=date_str, steps=steps)

    def write_medal(self, nickname: str, date: datetime, symbol: str) -> None:
        """Append *symbol* to the existing steps cell for (nickname, date).

        E.g. if the cell contains "11000", it becomes "11000 🥇".
        If the cell is empty the symbol is written as-is.
        """
        sheet = self._get_sheet()
        nickname = self._normalise_nick(nickname)
        date_str = date.strftime("%d.%m.%Y")

        all_values = sheet.get_all_values()
        col_idx, row_idx = self._ensure_cell(sheet, all_values, nickname, date_str)

        # Read current value and append medal symbol
        current = ""
        try:
            current = all_values[row_idx][col_idx] if col_idx < len(all_values[row_idx]) else ""
        except IndexError:
            pass

        # Strip any previously written medal symbol before re-writing
        # (idempotency when job runs more than once)
        for s in ("🥇", "🥈", "🥉"):
            current = current.replace(s, "").strip()

        new_value = f"{current} {symbol}".strip() if current else symbol
        sheet.update_cell(row_idx + 1, col_idx + 1, new_value)
        logger.info("Wrote medal to sheet", nickname=nickname, date=date_str, symbol=symbol)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_nick(nickname: str) -> str:
        return f"#{nickname}" if not nickname.startswith("#") else nickname

    def _ensure_cell(
        self,
        sheet: gspread.Worksheet,
        all_values: list[list[str]],
        nickname: str,
        date_str: str,
    ) -> tuple[int, int]:
        """Return (col_idx, row_idx) for (nickname, date_str), creating them if needed.

        Both indices are 0-based; add 1 when calling update_cell().
        """
        if not all_values:
            sheet.update("A1", [["Nick"]])
            all_values = [["Nick"]]

        headers = all_values[0]

        # --- locate or append date column ---
        col_idx: Optional[int] = None
        for i, header in enumerate(headers):
            if header == date_str:
                col_idx = i
                break

        if col_idx is None:
            col_idx = len(headers)
            sheet.update_cell(1, col_idx + 1, date_str)
            headers.append(date_str)
            logger.info("Created new date column", date=date_str, col=col_idx + 1)

        # --- locate or append nickname row ---
        row_idx: Optional[int] = None
        for i, row in enumerate(all_values):
            if i == 0:
                continue
            if row and row[0].lower() == nickname.lower():
                row_idx = i
                break

        if row_idx is None:
            row_idx = len(all_values)
            sheet.update_cell(row_idx + 1, 1, nickname)
            logger.info("Created new nickname row", nickname=nickname, row=row_idx + 1)

        return col_idx, row_idx

    def _get_sheet(self) -> gspread.Worksheet:
        spreadsheet = self._client.open_by_key(self._spreadsheet_id)
        try:
            return spreadsheet.worksheet(self._steps_worksheet)
        except gspread.WorksheetNotFound:
            logger.info("Worksheet not found, creating it", name=self._steps_worksheet)
            return spreadsheet.add_worksheet(title=self._steps_worksheet, rows=200, cols=50)
