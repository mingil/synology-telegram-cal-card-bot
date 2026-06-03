# ==========================================
# 1. Builder Stage (빌드 전용 환경)
# ==========================================
# 기존 3.9보다 훨씬 빠르고 효율적인 3.11 버전 사용
FROM python:3.11-slim AS builder

WORKDIR /build

# 패키지 컴파일에 필요한 도구 설치 (gcc 등)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

# 가상 환경(venv) 생성 및 패키지 설치
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==========================================
# 2. Runtime Stage (실제 실행 환경)
# ==========================================
FROM python:3.11-slim

# 파이썬 최적화 환경 변수 설정
# PYTHONUNBUFFERED=1: 로그를 버퍼링 없이 즉시 출력하여 시놀로지 로그창에서 실시간 확인 가능
# PYTHONDONTWRITEBYTECODE=1: 컨테이너 내부에 불필요한 .pyc 캐시 파일 생성 방지
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Seoul \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 타임존 설정용 패키지 (시간 동기화 오류 방지)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*

# Builder 스테이지에서 생성한 가상환경 복사 (gcc는 버리고 오므로 이미지 용량 대폭 감소)
COPY --from=builder /opt/venv /opt/venv

# 소스 코드 복사 (.dockerignore가 적용되어 깨끗한 코드만 복사됨)
COPY . .

# SQLite DB가 저장될 폴더 명시적 생성 (권한 꼬임 방지)
RUN mkdir -p /app/data

CMD ["python", "bot.py"]
