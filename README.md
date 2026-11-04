# 🤖 SynoCalBot (`bot-cal-card`): Telegram Assistant for Synology

![Python Version](https://img.shields.io/badge/python-3.11-blue.svg?logo=python)
![Docker](https://img.shields.io/badge/docker-optimized-2496ED.svg?logo=docker)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**SynoCalBot (`bot-cal-card`)** is a lightweight, self-hosted Telegram bot designed to seamlessly integrate with **Synology Calendar (CalDAV)**, **Synology Contacts (CardDAV)**, and **Google Gemini AI**.

Built specifically with Synology NAS (**Container Manager**, **Portainer**, and **Watchtower**) in mind, it helps you manage your schedules, search contacts, get conversational AI assistance, and receive smart daily notifications via Telegram and Email.

---

## ✨ Key Features

- **📅 Calendar Management (CalDAV)**
  - View daily (`/today`), weekly (`/week`), monthly (`/month`), or specific date (`/date`) schedules.
  - Search past and upcoming events by keyword (`/search_events`).
  - Add new events interactively via Telegram (`/addevent`).
- **👤 Contact Management (CardDAV)**
  - Quick search contacts by name (`/findcontact`).
  - Deep search contacts by phone number (with or without hyphens), email, organization, title, or memo (`/searchcontact`).
  - Add new contacts directly from the chat (`/addcontact`).
- **🤖 Conversational AI Assistant**
  - Integrated with Google Gemini API (`/ask`) supporting multi-turn contextual conversations as well as one-line queries (`/ask <question>`).
- **🔔 Smart Daily Notifications (Solar & Lunar)**
  - Automatically detects important anniversaries, birthdays, lunar dates, medical appointments, and billing cycles.
  - Converts Korean Lunar dates automatically and sends reminders on **D-30, D-7, D-1, and D-Day** without duplicates.
  - Sends morning briefings simultaneously via Telegram and Email (SMTP).
- **🛡️ Secure Access & Admin Controls**
  - Password-based authentication for new users with automatic ban after repeated failed attempts.
  - Interactive admin commands to **Ban** (`/ban`), **Unban** (`/unban`), **Permit** (`/permit`), or **Revoke** (`/revoke`) users.
- **🐳 Synology Docker & Watchtower Optimized**
  - Multi-stage lightweight Docker build (`python:3.11-slim`).
  - Automatic `PUID` / `PGID` mapping via `gosu` to prevent Synology shared folder permission issues.
  - SQLite `WAL` mode enabled to prevent database locks, with automatic pruning of old notification logs (>90 days).
  - Built-in log rotation (`RotatingFileHandler`, max 5MB × 3 files) to prevent NAS storage bloat.
  - Fully compatible with **Watchtower**, **Synology Container Manager**, and **Portainer** for seamless image updates.

---

## 🛠️ Prerequisites

1. **Telegram Bot Token (`TELEGRAM_BOT_TOKEN`)** from [@BotFather](https://t.me/BotFather).
2. **Telegram User/Chat ID (`TARGET_CHAT_ID`)** from [@userinfobot](https://t.me/userinfobot).
3. **Synology NAS** with **Synology Calendar** and **Synology Contacts** installed.
4. **Container Manager** (or Docker / Portainer) installed on your Synology NAS.
5. *(Optional)* **Google Gemini API Key (`GOOGLE_API_KEY`)** from [Google AI Studio](https://aistudio.google.com/).
6. *(Optional)* **Email App Password (`SMTP_PASSWORD`)** for SMTP email notifications (e.g., Gmail or Naver 2FA App Password).

---

## 🚀 Installation & Setup

You can deploy **SynoCalBot** either directly from **Docker Hub** (recommended, no source code required) or by building from source.

### Option A: Quick Start with Docker Hub Image (Recommended)

Ideal for **Synology Container Manager**, **Portainer**, and **Watchtower**.

1. Create a directory on your NAS (e.g., `/volume1/docker/bot-cal-card` and `/volume1/docker/bot-cal-card/data`).
2. Create a `.env` file in that directory using [`.env.example`](./.env.example) as a template.
3. Deploy using the following `docker-compose.yaml`:

```yaml
services:
  bot:
    container_name: bot-cal-card
    image: kimmingil/bot-cal-card:latest
    restart: unless-stopped
    env_file: .env
    environment:
      - TZ=Asia/Seoul
      - PUID=1026
      - PGID=100
    volumes:
      - ./data:/app/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

```bash
docker compose up -d
```

> 💡 **Automatic Updates:** Because this setup uses the official Docker Hub image (`kimmingil/bot-cal-card:latest`) and isolates persistent data in `./data`, tools like **Watchtower**, **Container Manager**, and **Portainer** can automatically pull and update the container whenever a new version is released.

---

### Option B: Clone & Build from Source

If you want to customize the code and build the image locally:

#### 1. Clone the repository
```bash
git clone https://github.com/mingil/synology-telegram-cal-card-bot.git bot-cal-card
cd bot-cal-card
```

#### 2. Configure environment variables
```bash
cp .env.example .env
```
Open `.env` and fill in your Telegram token, Synology CalDAV/CardDAV credentials, and optional Gemini/SMTP settings. *(Never commit your `.env` file to version control!)*

#### 3. Build and run with Docker Compose
```bash
docker compose up -d --build
```

Send `/start` to your bot on Telegram to open the main menu!

---

## 🎮 Bot Commands

**[General]**
* `/start` - Start the bot and open the interactive main menu
* `/help` - Show all available commands
* `/cancel` - Cancel the current action or conversation

**[Calendar]**
* `/today` - Show today's schedule
* `/week` - Show this week's schedule
* `/month` - Show this month's schedule
* `/date` - Show schedule for a specific date (`YYYY-MM-DD`)
* `/search_events` - Search calendar events by keyword
* `/addevent` - Add a new event to a selected calendar

**[Contacts]**
* `/findcontact` - Search contacts by name
* `/searchcontact` - Deep search contacts (by phone, email, organization, note, etc.)
* `/addcontact` - Add a new contact to Synology Contacts

**[AI Assistant]**
* `/ask` - Start a contextual conversation with Google Gemini AI (or `/ask <question>` for an immediate answer)

**[Admin Controls]** *(Restricted to `TARGET_CHAT_ID`)*
* `/banlist` / `/permitlist` - View blocked or permitted user IDs
* `/ban` / `/unban` - Block or unblock a user ID interactively
* `/permit` / `/revoke` - Grant or revoke access for a user ID interactively

---

## 📂 Project Structure

```text
.
├── bot.py                  # Main entry point and unified conversation handler
├── core/                   # Environment configuration and SQLite (WAL) database
├── data/                   # Persistent volume for SQLite DB and rotating logs
├── handlers/               # Telegram command & conversation handlers
├── services/               # CalDAV, CardDAV, SMTP Email, and Daily Notification services
├── utils/                  # Timezone, Korean Lunar calendar, and HTML formatters
├── tests/                  # Automated unit test suite (pytest)
├── docker-compose.yaml     # Standard Docker Compose configuration
└── Dockerfile              # Multi-stage Docker build optimized for Python 3.11
```

---

## 💡 Troubleshooting

* **CalDAV / CardDAV Login Issues:** Verify that `CALDAV_URL` and `CARDDAV_URL` in your `.env` file exactly match the URLs shown in your Synology Calendar and Synology Contacts client settings.
* **Email Notifications Failing:** Standard account passwords are blocked by 2FA policies on Gmail and Naver. Generate and use a dedicated **2FA App Password** for `SMTP_PASSWORD`.
* **Lunar Event Reminders:** Include the keyword `음력` in the event title (e.g., `음력 어머니 생신`) and register it on the lunar month/day in your calendar. The bot automatically calculates the corresponding solar date each year and sends reminders on D-30, D-7, D-1, and D-Day.

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.
