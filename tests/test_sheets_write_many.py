from datetime import datetime
from unittest.mock import MagicMock

import pytest

from bot.sheets import NicknameNotFoundError, SheetsService


def _service(values: list[list[str]]) -> tuple[SheetsService, MagicMock]:
    sheet = MagicMock()
    sheet.get_all_values.return_value = values
    service = SheetsService.__new__(SheetsService)
    service._get_sheet = lambda date: sheet
    return service, sheet


JUNE = [
    ["ИЮНЬ"],
    ["Ник", "21.06", "22.06", "23.06", "24.06"],
    ["#alice"],
    ["#CuriousCat"],
]


def test_write_steps_many_single_batch():
    service, sheet = _service(JUNE)
    service.write_steps_many("CuriousCat", [
        (datetime(2026, 6, 21), 100),
        (datetime(2026, 6, 22), 200),
        (datetime(2026, 6, 23), 5),
        (datetime(2026, 6, 24), 1943),
    ])
    sheet.batch_update.assert_called_once()
    updates = sheet.batch_update.call_args.args[0]
    assert updates == [
        {"range": "B4", "values": [[100]]},
        {"range": "C4", "values": [[200]]},
        {"range": "D4", "values": [[5]]},
        {"range": "E4", "values": [[1943]]},
    ]


def test_write_steps_many_unknown_nick_writes_nothing():
    service, sheet = _service(JUNE)
    with pytest.raises(NicknameNotFoundError):
        service.write_steps_many("bob", [(datetime(2026, 6, 21), 1)])
    sheet.batch_update.assert_not_called()


def test_write_steps_many_missing_date_column_writes_nothing(monkeypatch):
    monkeypatch.setattr("bot.decorators.time.sleep", lambda _: None)
    service, sheet = _service(JUNE)
    with pytest.raises(ValueError):
        service.write_steps_many("alice", [
            (datetime(2026, 6, 24), 1),
            (datetime(2026, 6, 25), 2),
        ])
    sheet.batch_update.assert_not_called()
