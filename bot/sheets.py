from datetime import datetime
from typing import Optional

import gspread
import structlog
from google.oauth2.service_account import Credentials

logger = structlog.get_logger()

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsService:
    """Read/write helper for the step-tracking Google Sheet.

    Expected sheet layout (Sheet 1):
        A1        | B1         | C1         | ...
        Nick      | DD.MM.YYYY | DD.MM.YYYY | ...
        vasya     | 8500       |            | ...
        petya     |            | 12000      | ...

    If the requested nickname row or date column does not exist, it is
    appended automatically.
    """

    def __init__(self, credentials_path: str, spreadsheet_id: str) -> None:
        creds = Credentials.from_service_account_file(
            credentials_path, scopes=_SCOPES
        )
        self._client = gspread.authorize(creds)
        self._spreadsheet_id = spreadsheet_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_steps(self, nickname: str, date: datetime, steps: int) -> None:
        """Write *steps* into the cell (nickname, date), creating row/column if needed."""
        sheet = self._get_sheet()
        date_str = date.strftime("%d.%m.%Y")

        all_values = sheet.get_all_values()

        # Bootstrap: create header row if sheet is completely empty
        if not all_values:
            sheet.update("A1", [["Nick"]])
            all_values = [["Nick"]]

        headers = all_values[0]

        # --- locate or append date column ---
        date_col_idx: Optional[int] = None
        for i, header in enumerate(headers):
            if header == date_str:
                date_col_idx = i
                break

        if date_col_idx is None:
            date_col_idx = len(headers)
            sheet.update_cell(1, date_col_idx + 1, date_str)
            headers.append(date_str)
            logger.info("Created new date column", date=date_str, col=date_col_idx + 1)

        # --- locate or append nickname row ---
        nick_row_idx: Optional[int] = None
        for i, row in enumerate(all_values):
            if i == 0:
                continue  # skip header
            if row and row[0].lower() == nickname.lower():
                nick_row_idx = i
                break

        if nick_row_idx is None:
            nick_row_idx = len(all_values)
            sheet.update_cell(nick_row_idx + 1, 1, nickname)
            logger.info("Created new nickname row", nickname=nickname, row=nick_row_idx + 1)

        # --- write step count ---
        sheet.update_cell(nick_row_idx + 1, date_col_idx + 1, steps)
        logger.info(
            "Wrote steps to sheet",
            nickname=nickname,
            date=date_str,
            steps=steps,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_sheet(self) -> gspread.Worksheet:
        spreadsheet = self._client.open_by_key(self._spreadsheet_id)
        return spreadsheet.sheet1
