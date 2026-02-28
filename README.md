<p align="center">
  <img src="easygo_avatar.png" alt="EasyGo Tracker" width="200"/>
</p>

# EasyGo Tracker

A Telegram bot that collects daily step-count reports from a fitness challenge channel, persists them to MongoDB and Google Sheets, and answers questions via an optional OpenAI-powered assistant.

## Features

- **Step report parsing** — members post free-form `#отчет` messages; the bot extracts nickname, date, and step count regardless of word order.
- **Google Sheets sync** — each accepted report is written to a shared spreadsheet (rows = nicknames, columns = dates). Missing rows and columns are created automatically.
- **MongoDB storage** — reports are also stored in MongoDB for fast aggregation queries. Raw channel messages are stored with a 24-hour TTL.
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

- **Nickname** — first `#tag` that is not `#отчет` / `#отчёт`.
- **Date** — first `d.m`, `d.m.yy`, or `d.m.yyyy` pattern. Defaults to today (UTC) when omitted.
- **Steps** — first standalone integer after removing the date and all hashtags.

| Validation failure | Bot response |
|---|---|
| No `#nickname` | `Отсутствует #ник` |
| No step count | `Отсутствует количество шагов` |
| Sheets write error | `Ошибка сохранения данных` |
| All OK | `#nickname - принято` |

## Bot Commands (via @mention)

Mention the bot in the channel to trigger these commands:

| Message | Response |
|---|---|
| `@BotName today-top` | Top-5 step counts for today |
| `@BotName month-top` | Top-5 total steps for the current month |
| `@BotName totals` | All-time step totals per participant |
| `@BotName <any question>` | AI-powered answer (requires `OPENAI_API_KEY`) |

## Project Structure

```
bot/
├── main.py        # Entry point: registers handlers, startup/shutdown hooks
├── config.py      # Pydantic-settings: loads all env vars
├── handlers.py    # Message routing: report processing, leaderboards, AI queries
├── parser.py      # parse_report(): extracts nickname, date, steps from free text
├── models.py      # Beanie documents: TelegramMessage, TelegramUser, StepReport
├── database.py    # MongoDB connection manager (motor + beanie)
├── sheets.py      # SheetsService: read/write Google Sheets via gspread
├── ai.py          # AIService: two-step classify → fetch context → answer
└── utils/
    ├── logger.py  # structlog setup
    └── version.py
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

| Variable | Description |
|---|---|
| `TELEGRAM_API_KEY` | Token from @BotFather |
| `ALLOWED_CHAT_IDS` | Comma-separated channel IDs the bot responds to |
| `MONGODB_URI` | MongoDB connection string |
| `GOOGLE_SHEET_ID` | Spreadsheet ID from the sheet URL |
| `GOOGLE_CREDENTIALS_PATH` | Path to service account JSON (default: `credentials.json`) |
| `OPENAI_API_KEY` | Optional. Enables the AI assistant feature |
| `OPENAI_MODEL` | Model to use (default: `gpt-4o-mini`) |
| `LOG_LEVEL` | `INFO` or `DEBUG` (default: `INFO`) |

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

The bot maintains Sheet 1 of the configured spreadsheet:

| Nick | 25.02.2026 | 26.02.2026 | … |
|------|-----------|-----------|---|
| #vasya | 8500 | | |
| #petya | | 12000 | |

- Row 1 is the header: `Nick` in A1, then date strings (`DD.MM.YYYY`) in subsequent columns.
- Missing nickname rows and date columns are appended automatically.

## Running Tests

```bash
pytest
```
