# 🤖 Synology Telegram Cal-Card Bot (v2.2)

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
![Synology](https://img.shields.io/badge/Synology-DSM7-darkblue?logo=synology&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

A powerful Telegram bot designed for **Synology NAS**. It integrates with **Synology Calendar (CalDAV)** and **Contacts (CardDAV)** to provide automated reminders, search functionality, and **Korean Lunar Birthday** calculations.

시놀로지 NAS를 위한 강력한 텔레그램 봇입니다. **캘린더(CalDAV)** 및 **연락처(CardDAV)**와 연동되어 일정 알림, 검색 기능을 제공하며, 특히 매년 변하는 **음력 생일**을 자동으로 계산하여 알려줍니다.

> **v2.2 Update:** 관리자 기능이 대화형(Interactive)으로 강화되었으며, 연락처 상세 조회 및 구조적 리팩토링이 완료되었습니다.

---

## ✨ Key Features (주요 기능)

- 📅 **Smart Reminders**: 일정 하루 전, 당일 등 맞춤형 자동 알림 발송.
- 🌕 **Lunar Birthday Support**: 캘린더 제목에 `(음력)` 포함 시, 매년 변하는 음력 날짜를 자동 계산하여 알림.
- 🔍 **Instant Search**: 텔레그램 채팅창에서 바로 일정 키워드 검색.
- 👤 **Detailed Contact Info**: 이름, 전화번호뿐만 아니라 **주소, 회사, 직함, 메모**까지 상세 정보 조회.
- 🧠 **AI Integration**: Google Gemini AI와 연동하여 봇과 대화 가능.
- 🛡️ **Security**: 비밀번호 인증 시스템 및 차단/허용 관리 기능 탑재.

---

## 🏗️ Project Structure (프로젝트 구조)

이 프로젝트는 **관심사의 분리(SoC)** 원칙에 따라 모듈화되어 있습니다.

```text
bot-cal-card/
├── core/                  # 프로젝트 설정 및 데이터베이스
│   ├── config.py          # 환경변수 로드
│   └── database.py        # SQLite DB 관리 (알림 중복 방지, 유저 관리)
│
├── services/              # 핵심 비즈니스 로직
│   ├── caldav_service.py  # 캘린더 연동 (CalDAV)
│   ├── carddav_service.py # 연락처 연동 (CardDAV)
│   └── notification.py    # 알림 스케줄링 및 음력 계산 로직
│
├── handlers/              # 텔레그램 명령어 핸들러
│   ├── auth.py            # 인증 및 관리자 기능
│   ├── calendar.py        # 일정 조회/추가/삭제
│   ├── contact.py         # 연락처 검색/추가
│   └── common.py          # 공통 기능 및 도움말
│
├── utils/                 # 유틸리티 함수
│   ├── date_utils.py      # 날짜 계산 및 변환
│   └── formatters.py      # 메시지 HTML 포맷팅
│
└── bot.py                 # 메인 실행 파일 (Application 진입점)

🚀 Installation (설치 방법)
1. Prerequisites
Synology NAS (Docker support) or any Linux Server

Telegram Bot Token

Google Gemini API Key (Optional)

2. Setup with Docker Compose
Clone this repository.

Create .env file from example.

Bash

cp .env.example .env
Edit .env and fill in your information.

Run container.

Bash

docker-compose up -d --build

💬 Commands (명령어 목록)
Command,Description
/start,"봇 시작 및 인증, 메인 메뉴 호출"
/help,전체 명령어 도움말 보기
/today,오늘 일정 조회
/week,이번 주 일정 조회
/month,이번 달 일정 조회
/date,특정 날짜 일정 조회
/search_events,일정 키워드 검색
/addevent,새 일정 추가 (대화형)
/findcontact,연락처 이름 검색
/searchcontact,"연락처 상세 검색 (전화번호, 회사 등)"
/addcontact,새 연락처 추가
/ask,AI에게 질문하기
/cancel,현재 진행 중인 작업 취소
Admin Only,관리자 전용 기능
/ban,사용자 차단 (대화형)
/unban,차단 해제 (대화형)
/permit,권한 부여 (대화형)
/revoke,권한 취소 (대화형)
/banlist,차단된 사용자 목록 조회
/permitlist,승인된 사용자 목록 조회

🛠️ Development
Requirements
Python 3.9+

requirements.txt dependencies

Local Run
Bash

pip install -r requirements.txt
python bot.py

📝 License
This project is licensed under the MIT License.