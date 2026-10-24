<p align="center">
  <img src="easygo_avatar.png" alt="EasyGo Tracker" width="200"/>
</p>

# EasyGo Tracker

A Telegram bot that collects daily step-count reports from a fitness challenge channel, persists them to MongoDB and Google Sheets, awards daily medals, and answers questions via an optional OpenAI-powered assistant.

## Features

- **Step report parsing** — members post free-form `#отчет` messages; the bot extracts nickname, date, and step count regardless of word order.
- **Google Sheets sync** — each accepted report is written to a shared spreadsheet (rows = nicknames, columns = dates). The target worksheet is configurable via `WORKSHEET_NAME`. Missing rows and columns are created automatically.
- **Daily medals** — every day at 20:00 MSK the bot ranks participants by step count using dense ranking and awards 🥇 gold / 🥈 silver / 🥉 bronze. Tied participants share the same medal. The medal symbol is appended to the participant's step-count cell in the sheet (e.g. `11 000 🥇`) and the result is posted to the configured report channel.
- **Disk space monitoring** — every 5 minutes the bot checks free disk space and, if it drops below the configured threshold (100 MB by default), posts a randomly chosen complaint to the report channel.
- **MongoDB storage** — reports and medals are stored in MongoDB for fast aggregation queries. Raw channel messages are stored with a 24-hour TTL.
- **Nickname memory** — once a user submits a report with a `#nickname`, the bot remembers it; subsequent reports from the same Telegram account do not need to include the tag again.
- **Leaderboards** — mention the bot with `today-top`, `month-top`, or `totals` to get ranked summaries.
- **AI assistant** — mention the bot with any free-form question and it routes the query to OpenAI, fetching relevant context (message history, per-user steps, or all-user steps) automatically.
- **Channel-safe** — works in Telegram channels where updates arrive as `channel_post` rather than `message`.
- **Allowlist** — optionally restrict the bot to a specific list of chat/channel IDs.

## Tech Stack

| Layer | Library |
|---|---|
| Telegram | python-telegram-bot 20.7 |
| Database | MongoDB 7 · motor 3.4 · beanie 1.25 |
| Sheets | gspread 6 · google-auth 2 |
| AI | openai ≥ 1.0 (optional) |
| Config | pydantic-settings 2 · python-dotenv |
| Logging | structlog |
| Runtime | Python 3.11+ · Docker + Compose |

## Report Format

```
#отчет #nickname dd.mm.yyyy number_of_steps
```

Components may appear in **any order**:

```
#отчет #vasya 25.02.2026 12000
#Отчет 12000 #petya 25.02.2026
25.02.2026 #отчет 8500 #masha
```

- **Nickname** — the only `#tag` that is not a service tag (`#отчет` / `#отчёт` / `#ачивка`). If several different non-service tags are present, the report is rejected as ambiguous.
- **Date** — first `d.m`, `d.m.yy`, or `d.m.yyyy` pattern. Defaults to today (UTC) when omitted.
- **Steps** — first standalone integer after removing the date and all hashtags.

### Multi-day reports

Several days can be reported at once with a date range (both ends inclusive) and a comma-separated list of step counts, one per day:

```
#отчет #CuriousCat 21.06-24.06 100,200,5,1943
```

- The number of step values must equal the number of days in the range, otherwise the report is rejected.
- Ranges longer than 31 days, ranges whose start is after the end, and dates outside the current year or in the future are rejected.
- All cells are checked before writing, so a rejected report never leaves a partially filled range.

| Validation failure | Bot response |
|---|---|
| No `#nickname` | `Отсутствует #ник` |
| No step count | `Отсутствует количество шагов` |
| Several `#nicknames` | `Непонятно, чей это отчёт: несколько ников (#a, #b)…` |
| Range: step values ≠ days | `Количество значений шагов (3) не совпадает с числом дней 21.06–24.06 (4)` |
| Range: start after end / invalid date | `Недопустимый диапазон дат…` |
| Sheets write error | `Ошибка сохранения данных` |
| All OK | `#nickname - принято` (range: `#nickname - принято (21.06–24.06, дней: 4)`) |

## Bot Commands (via @mention)

Mention the bot in the channel to trigger these commands:

| Message | Response |
|---|---|
| `@BotName today-top` | Top-5 step counts for today |
| `@BotName month-top` | Top-5 total steps for the current month |
| `@BotName totals` | All-time step totals per participant |
| `@BotName <any question>` | AI-powered answer (requires `OPENAI_API_KEY`) |

## Daily Medal Assignment

Every day at **20:00 MSK** the bot:

1. Queries all step reports for the previous MSK calendar day.
2. Sorts participants descending by step count using **dense ranking** — tied step counts share the same medal position.
3. Awards medals to the top 3 distinct step values:

| Rank | Medal |
|---|---|
| 1st | 🥇 Gold |
| 2nd | 🥈 Silver |
| 3rd | 🥉 Bronze |

**Example:** steps `11 000 / 11 000 / 10 500 / 500` → both users with 11 000 receive 🥇, the user with 10 500 receives 🥈, the user with 500 receives 🥉.

The medal symbol is **appended to the step-count cell** in the steps sheet (e.g. `11 000 🥇`) and a summary is posted to `REPORT_CHANNEL_ID`:

```
Медали за 01.03.2026:
🥇 #vasya, #petya — 11 000 шагов
🥈 #masha — 10 500 шагов
🥉 #kolya — 500 шагов
```

Medal records are also stored in the `medals` MongoDB collection for historical queries.

## Project Structure

```
bot/
├── main.py        # Entry point: registers handlers, startup/shutdown, job schedule
├── config.py      # Pydantic-settings: loads all env vars
├── handlers.py    # Message routing: report processing, leaderboards, AI queries
├── parser.py      # parse_report(): extracts nickname, date, steps from free text
├── models.py      # Beanie documents: TelegramMessage, TelegramUser, StepReport, MedalRecord
├── database.py    # MongoDB connection manager (motor + beanie)
├── sheets.py      # SheetsService: read/write Google Sheets via gspread
├── medals.py      # Daily medal assignment job + channel report
├── disk_monitor.py # Periodic free-disk-space check + low-space alert
├── ai.py          # AIService: two-step classify → fetch context → answer
└── utils/
    ├── logger.py  # structlog setup
    └── version.py
utils/
└── trigger_medal_report.py  # CLI utility to manually trigger medal assignment
docker-compose.yml
Dockerfile
pyproject.toml
.env.example
DEPLOY.md          # Full GCP + Docker deployment guide
```

## Quick Start (Local)

### Prerequisites

- Python 3.11+
- MongoDB instance (or use Docker Compose)
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Google Sheets service account credentials (`credentials.json`)

### 1. Install dependencies

```bash
pip install uv
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_API_KEY` | ✅ | — | Token from @BotFather |
| `ALLOWED_CHAT_IDS` | — | *(all)* | Comma-separated channel IDs the bot responds to |
| `MONGODB_URI` | ✅ | — | MongoDB connection string |
| `GOOGLE_SHEET_ID` | ✅ | — | Spreadsheet ID from the sheet URL |
| `GOOGLE_CREDENTIALS_PATH` | — | `credentials.json` | Path to service account JSON |
| `WORKSHEET_NAME` | — | `Шаги` | Name of the steps worksheet inside the spreadsheet |
| `REPORT_CHANNEL_ID` | — | *(disabled)* | Channel ID to post daily medal summaries |
| `DISK_CHECK_PATH` | — | `.` | Path whose filesystem is monitored for free space |
| `DISK_FREE_THRESHOLD_MB` | — | `100` | Post a complaint to `REPORT_CHANNEL_ID` when free space drops below this |
| `DISK_CHECK_INTERVAL_MINUTES` | — | `5` | How often to check free space |
| `DISK_ALERT_REPEAT_MINUTES` | — | `60` | Minimum interval between repeated alerts while space stays low |
| `OPENAI_API_KEY` | — | *(disabled)* | Enables the AI assistant feature |
| `OPENAI_MODEL` | — | `gpt-4o-mini` | OpenAI model to use |
| `LOG_LEVEL` | — | `INFO` | `INFO` or `DEBUG` |

### 3. Run

```bash
python -m bot.main
```

## Docker Compose

```bash
# Start bot + MongoDB
docker compose up -d --build

# View logs
docker compose logs -f bot

# Stop
docker compose down
```

The MongoDB container uses a named volume (`mongodb_data`) so data persists across restarts. See [`DEPLOY.md`](DEPLOY.md) for full GCP deployment instructions.

## Google Sheets Layout

The bot maintains the configured worksheet (`WORKSHEET_NAME`, default `Шаги`):

| Nick | 25.02.2026 | 26.02.2026 | … |
|------|-----------|-----------|---|
| #vasya | 8 500 | 9 000 🥈 | |
| #petya | 12 000 🥇 | | |

- Row 1 is the header: `Nick` in A1, then date strings (`DD.MM.YYYY`) in subsequent columns.
- Missing nickname rows and date columns are appended automatically.
- After the daily medal job runs, the winning cell is updated in-place: `12 000` becomes `12 000 🥇`.
- The worksheet is created automatically if it does not exist.

## MongoDB Collections

| Collection | Document | TTL |
|---|---|---|
| `messages` | Raw Telegram messages (`TelegramMessage`) | 24 hours |
| `users` | Persistent nickname profiles (`TelegramUser`) | none |
| `reports` | Parsed step reports (`StepReport`) | none |
| `medals` | Daily medal records (`MedalRecord`) | none |

## Utilities

### Manually trigger medal assignment

Useful when the scheduled job was missed (e.g. after a deployment restart):

```bash
# Inside the running container
docker exec -it tracker_bot python -m utils.trigger_medal_report

# Or locally (with .env configured)
python -m utils.trigger_medal_report
```

The script connects to MongoDB and Sheets using the same settings as the bot, runs the full medal logic for the previous MSK day, and posts the summary to `REPORT_CHANNEL_ID` if configured.

## Running Tests

```bash
pytest
```
