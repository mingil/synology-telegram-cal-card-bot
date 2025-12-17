# /volume1/docker/bot-cal-card/Dockerfile
FROM python:3.9-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# [중요] 현재 폴더의 모든 파일을 그냥 다 복사 (구조 변경 X)
COPY . .

# 데이터 폴더 생성
RUN mkdir -p /app/data

CMD ["python", "bot.py"]