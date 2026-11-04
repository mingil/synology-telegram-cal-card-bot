# ==========================================
# 1. Builder Stage
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==========================================
# 2. Runtime Stage
# ==========================================
FROM python:3.11-slim

LABEL org.opencontainers.image.title="SynoCalBot (bot-cal-card)" \
      org.opencontainers.image.description="Telegram Assistant for Synology Calendar (CalDAV), Contacts (CardDAV), and Gemini AI" \
      org.opencontainers.image.source="https://github.com/mingil/synology-telegram-cal-card-bot" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Seoul \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 타임존 및 시놀로지 NAS 권한 매핑(PUID/PGID)을 위한 최소 패키지 설치
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata gosu procps && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY . .

RUN mkdir -p /app/data

# 표준 Docker 엔트리포인트: 데이터 폴더 권한을 맞춘 뒤 exec로 PID 1을 python에 위임 (Watchtower/Portainer 정상 종료 신호 수신)
RUN { \
    echo '#!/bin/bash'; \
    echo 'set -e'; \
    echo 'PUID=${PUID:-1026}'; \
    echo 'PGID=${PGID:-100}'; \
    echo 'groupadd -o -g "$PGID" botgroup 2>/dev/null || true'; \
    echo 'useradd -o -u "$PUID" -g "$PGID" -s /bin/sh -d /app botuser 2>/dev/null || true'; \
    echo 'chown -R "$PUID:$PGID" /app/data 2>/dev/null || true'; \
    echo 'exec gosu "$PUID:$PGID" python bot.py'; \
} > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD pgrep -f "python bot.py" > /dev/null || exit 1

VOLUME ["/app/data"]

ENTRYPOINT ["/app/entrypoint.sh"]
