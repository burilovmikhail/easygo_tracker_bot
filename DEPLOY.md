# EasyGo Tracker — Deployment Guide

## Overview

The bot runs as a Docker container alongside a MongoDB container. It needs:
1. A Telegram Bot token
2. A running MongoDB instance
3. A Google Sheets service-account key and the target spreadsheet ID

---

## 1. Telegram Setup

1. Open [@BotFather](https://t.me/BotFather) in Telegram.
2. Send `/newbot` and follow the prompts.
3. Copy the API token — this becomes `TELEGRAM_API_KEY` in `.env`.
4. Add the bot to your channel as an **administrator** with permission to **Post Messages**.

---

## 2. Google Cloud Setup (Sheets API + Service Account)

### 2.1 Create / Select a GCP Project

1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/).
2. Click the project selector → **New Project** (e.g. `easygo-tracker`).

### 2.2 Enable the Google Sheets API

```
APIs & Services → Library → search "Google Sheets API" → Enable
```

### 2.3 Create a Service Account

```
IAM & Admin → Service Accounts → Create Service Account
```

- **Name:** `easygo-tracker-bot`
- **Role:** `Editor` (or `Sheets Editor` if you prefer a narrower scope)
- Click **Done** — no need to grant user access.

### 2.4 Download the JSON Key

1. Click the service account you just created.
2. **Keys** tab → **Add Key → Create new key → JSON**.
3. Save the downloaded file as **`credentials.json`** in the project root (next to `docker-compose.yml`).

> The file is gitignored by default. Never commit it to version control.

### 2.5 Share the Google Sheet with the Service Account

1. Open your Google Sheet.
2. Click **Share**.
3. Paste the service account email (looks like `easygo-tracker-bot@your-project.iam.gserviceaccount.com`).
4. Grant **Editor** access and click **Send**.

### 2.6 Get the Spreadsheet ID

From the sheet URL:
```
https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
```
Copy `<SPREADSHEET_ID>` — this becomes `GOOGLE_SHEET_ID` in `.env`.

### 2.7 Sheet Structure

The bot expects (and can bootstrap) this layout on Sheet 1:

| A (Nick) | B (DD.MM.YYYY) | C (DD.MM.YYYY) | … |
|----------|---------------|---------------|---|
| vasya    | 8500          |               |   |
| petya    |               | 12000         |   |

- **Row 1** — header row: `Nick` in A1, then date strings (`25.02.2026`) in subsequent columns.
- **Column A** — one nickname per row (without the `#`).
- If a nickname or date column is missing, the bot creates it automatically.

---

## 3. Environment Configuration

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|---|---|
| `TELEGRAM_API_KEY` | Token from @BotFather |
| `MONGODB_URI` | `mongodb://easygo_user:easygo_pass@mongodb:27017/easygo_bot?authSource=admin` |
| `MONGO_INITDB_ROOT_USERNAME` | MongoDB user created on first run |
| `MONGO_INITDB_ROOT_PASSWORD` | MongoDB password |
| `MONGO_INITDB_DATABASE` | MongoDB database name |
| `GOOGLE_SHEET_ID` | Spreadsheet ID from the sheet URL |
| `GOOGLE_CREDENTIALS_PATH` | Path inside the container — keep as `credentials.json` |
| `LOG_LEVEL` | `INFO` or `DEBUG` |

---

## 4. Deploy with Docker Compose

### Prerequisites

- Docker ≥ 24 and Docker Compose plugin
- `credentials.json` in the project root
- `.env` filled in

### Start

```bash
docker compose up -d --build
```

### Verify

```bash
docker compose ps          # both services should show "running"
docker compose logs -f bot # watch bot logs
```

### Stop

```bash
docker compose down
```

### Update Bot Code

```bash
git pull
docker compose up -d --build bot
```

---

## 5. Deploy on a GCP VM (Compute Engine)

### 5.1 Create the VM

```
Compute Engine → VM Instances → Create Instance
```

Recommended spec for this workload:
- **Machine type:** `e2-micro` (free tier eligible)
- **OS:** Debian 12 or Ubuntu 22.04 LTS
- **Boot disk:** 20 GB standard
- **Firewall:** no inbound ports required (bot uses outbound polling)

### 5.2 Install Docker

```bash
# SSH into the VM
gcloud compute ssh <INSTANCE_NAME>

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### 5.3 Copy Project Files

From your local machine:

```bash
gcloud compute scp --recurse . <INSTANCE_NAME>:~/easygo-tracker \
    --exclude=".venv,.git"
```

Or clone from Git:

```bash
git clone <your-repo-url> ~/easygo-tracker
cd ~/easygo-tracker
```

Upload `credentials.json` separately (never commit it):

```bash
gcloud compute scp credentials.json <INSTANCE_NAME>:~/easygo-tracker/credentials.json
```

### 5.4 Configure and Start

```bash
cd ~/easygo-tracker
cp .env.example .env
nano .env          # fill in all values
docker compose up -d --build
```

### 5.5 Auto-start on VM Reboot

Docker Compose services have `restart: unless-stopped`, so they restart automatically after a reboot. Nothing extra is needed.

---

## 6. MongoDB Notes

The MongoDB container uses a named volume (`mongodb_data`) so data persists across container restarts and rebuilds. Messages are stored for **24 hours** via a TTL index on the `date` field — no manual cleanup required.

To inspect the database:

```bash
docker exec -it tracker_mongodb mongosh \
  -u easygo_user -p easygo_pass \
  --authenticationDatabase admin \
  easygo_bot
```

---

## 7. Bot Message Format

```
#отчет #nickname dd.mm.yyyy number_of_steps
```

Components may appear in **any order**. Examples:

```
#отчет #vasya 25.02.2026 12000
#Отчет 12000 #petya 25.02.2026
25.02.2026 #отчет 8500 #masha
```

| Validation failure | Bot response |
|---|---|
| No `#nickname` found | `Отсутствует #ник` |
| No step count found | `Отсутствует количество шагов` |
| Sheets write error | `Ошибка сохранения данных` |
| All OK | `#nickname - принято` |

If no date is present, today's date (UTC) is used.
