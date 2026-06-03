# 🤖 SynoCalBot: Telegram Assistant for Synology

![Python Version](https://img.shields.io/badge/python-3.11-blue.svg?logo=python)
![Docker](https://img.shields.io/badge/docker-optimized-2496ED.svg?logo=docker)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**SynoCalBot** is a highly optimized, self-hosted Telegram bot designed to seamlessly integrate with **Synology Calendar (CalDAV)**, **Synology Contacts (CardDAV)**, and **Google Gemini AI**.

Built specifically with Synology's Docker (Container Manager) environment in mind, it helps you manage your schedules, search contacts, get AI assistance, and receive smart daily notifications via Telegram and Email.

---

## ✨ Key Features

- **📅 Calendar Management (CalDAV)**
  - View daily, weekly, or monthly schedules.
  - Search events by keyword.
  - Add new events interactively via Telegram.
- **👤 Contact Management (CardDAV)**
  - Search contacts by name, email, phone number, or memo.
  - Add new contacts directly from the chat.
- **🤖 AI Assistant**
  - Integrated with Google Gemini API to answer questions naturally using the `/ask` command.
- **🔔 Smart Daily Notifications**
  - Automatically checks for important anniversaries, birthdays, lunar dates, and billing cycles.
  - Sends morning briefings via Telegram and Email (SMTP).
- **🛡️ Secure Access & Admin Controls**
  - Password-based authentication for new users.
  - Admins can interactively **Ban**, **Unban**, **Permit**, or **Revoke** users.
- **🐳 Synology Docker Optimized**
  - Multi-stage lightweight Docker build (Python 3.11).
  - Explicit volume mapping for persistent data without causing local sync conflicts.
  - SQLite WAL mode applied to prevent DB lock issues.
  - Log rotation enabled to prevent NAS storage bloat.

---

## 🛠️ Prerequisites

- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather)).
- Synology NAS with **Synology Calendar** and **Synology Contacts** installed.
- **Container Manager** (Docker) installed on your Synology NAS.
- (Optional) Google Gemini API Key for AI features.
- (Optional) Email App Password (2FA) for SMTP notifications.

---

## 🚀 Installation & Setup

We highly recommend running this bot via Docker Compose for maximum stability.

### 1. Clone the repository
```bash
git clone [https://github.com/yourusername/bot-cal-card.git](https://github.com/yourusername/bot-cal-card.git)
cd bot-cal-card

```

*(Replace `yourusername` with your actual GitHub username)*

### 2. Configure Environment Variables

Copy the example configuration file and fill in your details:

```bash
cp .env.example .env

```

Open `.env` and configure your Telegram token, Synology credentials, and SMTP settings. *(Note: Do not commit your `.env` file to version control!)*

### 3. Build & Run with Docker Compose

Deploy the bot in the background:

```bash
docker-compose up -d --build

```

That's it! Send `/start` to your bot on Telegram to begin.

---

## 🎮 Bot Commands

Here is the list of commands you can use in Telegram:

**[General]**

* `/start` - Start the bot and open the main menu
* `/help` - Show all available commands
* `/cancel` - Cancel the current action or conversation

**[Calendar]**

* `/today` - Show today's schedule
* `/week` - Show this week's schedule
* `/month` - Show this month's schedule
* `/date` - Show schedule for a specific date (YYYY-MM-DD)
* `/search_events` - Search calendar events by keyword
* `/addevent` - Add a new event to the calendar

**[Contacts]**

* `/findcontact` - Search contacts by name
* `/searchcontact` - Deep search contacts (by email, phone, note, etc.)
* `/addcontact` - Add a new contact to Synology Contacts

**[AI Assistant]**

* `/ask` - Ask the AI (Google Gemini) a question

**[Admin Controls]** *(Only available to Admin ID)*

* `/banlist` / `/permitlist` - View blocked or permitted users
* `/ban` / `/unban` - Block or unblock a user ID
* `/permit` / `/revoke` - Grant or revoke access to a user ID

---

## 📂 Project Structure

```text
.
├── bot.py                  # Main entry point for the Telegram bot
├── core/                   # Configuration and DB (SQLite) initialization
├── data/                   # Persistent volume for DB and logs
├── handlers/               # Telegram message & command handlers
├── services/               # CalDAV, CardDAV, Email, and Notification logic
├── utils/                  # Date formatting and utilities
├── docker-compose.yaml     # Docker orchestration
└── Dockerfile              # Multi-stage Docker build optimized for Python 3.11

```

---

## 💡 Troubleshooting

* **CalDAV/CardDAV Login Issues:** Verify that the URLs in your `.env` file exactly match the ones provided in your Synology Calendar/Contacts settings. If you use 2FA, create an **App Password** in Synology DSM.
* **Email Notifications Failing:** Ensure you are using an **App Password** for your Google or Naver account, as standard passwords are blocked by 2FA policies.

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](https://www.google.com/search?q=LICENSE) file for details.

```

---
