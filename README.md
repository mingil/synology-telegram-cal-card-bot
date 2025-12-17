# 🤖 Synology Telegram Cal-Card Bot

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
![Synology](https://img.shields.io/badge/Synology-DSM7-darkblue?logo=synology&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

A powerful Telegram bot designed for **Synology NAS**. It integrates with **Synology Calendar (CalDAV)** and **Contacts (CardDAV)** to provide automated reminders, search functionality, and **Korean Lunar Birthday** calculations.

시놀로지 NAS를 위한 강력한 텔레그램 봇입니다. **캘린더(CalDAV)** 및 **연락처(CardDAV)**와 연동되어 일정 알림, 검색 기능을 제공하며, 특히 매년 변하는 **음력 생일**을 자동으로 계산하여 알려줍니다.

---

## ✨ Key Features (주요 기능)

- 📅 **Smart Reminders**: Get notified 1 day, 1 hour, or 15 mins before events.  
  (스마트 알림: 일정 하루 전, 1시간 전, 15분 전 등 맞춤 알림 제공)
- 🌕 **Lunar Birthday Support**: Automatically calculates Korean Lunar dates. Just add "(음력)" to your event title!  
  (음력 지원: 캘린더 일정 제목에 "(음력)"만 넣으면 매년 자동으로 계산해서 알려줍니다.)
- 🔍 **Instant Search**: Search contacts and schedules directly from Telegram chat.  
  (즉시 검색: 채팅창에서 바로 연락처와 일정을 검색할 수 있습니다.)
- 🐳 **Docker Ready**: Easy installation via Docker Compose on Synology Container Manager.  
  (도커 지원: 시놀로지 컨테이너 매니저를 통해 간편하게 설치 가능합니다.)

---

## 🚀 Installation (설치 방법)

### 1. Clone Repository (저장소 다운로드)
Download this repository to your Synology NAS (via SSH or Download ZIP).
```bash
git clone [https://github.com/mingil/synology-telegram-cal-card-bot.git](https://github.com/mingil/synology-telegram-cal-card-bot.git)