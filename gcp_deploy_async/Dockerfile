FROM python:3.11-slim

# Chrome 및 의존성 설치
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Chrome 설치
RUN wget -q -O /tmp/google-chrome-stable_current_amd64.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get update && \
    apt-get install -y -f /tmp/google-chrome-stable_current_amd64.deb && \
    rm /tmp/google-chrome-stable_current_amd64.deb

# Chromedriver 설치 (최신 버전)
RUN set -eux; \
  CHROMEDRIVER_VERSION="$(curl -fsSL https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE)"; \
  echo "Chromedriver version: ${CHROMEDRIVER_VERSION}"; \
  wget -q -O /tmp/chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/${CHROMEDRIVER_VERSION}/linux64/chromedriver-linux64.zip"; \
  unzip -q /tmp/chromedriver.zip -d /tmp; \
  install -m 0755 /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver; \
  rm -rf /tmp/chromedriver*

WORKDIR /app

# Python unbuffered 모드 (실시간 로그 출력)
ENV PYTHONUNBUFFERED=1

# Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# Cloud Run Job 실행 (unbuffered 모드)
CMD ["python", "-u", "main.py"]
