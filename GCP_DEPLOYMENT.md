# GCP 서버리스 배포 가이드

`run_pipeline.py`를 GCP Cloud Run Jobs로 배포하여 주기적으로 자동 실행하는 방법입니다.

## 📋 목차

- [아키텍처 개요](#아키텍처-개요)
- [사전 준비](#사전-준비)
- [배포 구조](#배포-구조)
- [단계별 배포](#단계별-배포)
- [스케줄링 설정](#스케줄링-설정)
- [모니터링](#모니터링)
- [비용 추정](#비용-추정)

## 🏗️ 아키텍처 개요

```
Cloud Scheduler (매주 월요일 오전 9시)
    ↓
Cloud Run Job (run_pipeline.py 실행)
    ├── 1. Google News 크롤링
    ├── 2. LLM 분석
    └── 3. DART 매핑
    ↓
Google Sheets (결과 저장)
```

**장점:**
- 서버 관리 불필요
- 사용한 만큼만 과금 (실행 시간 기준)
- 자동 스케일링 및 오류 처리
- Secret Manager로 API 키 안전하게 관리

## 🔧 사전 준비

### 1. GCP 프로젝트 설정

```bash
# GCP CLI 설치 확인
gcloud --version

# 프로젝트 설정
export GCP_PROJECT_ID="your-project-id"
gcloud config set project $GCP_PROJECT_ID

# 필요한 API 활성화
gcloud services enable run.googleapis.com
gcloud services enable cloudscheduler.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable artifactregistry.googleapis.com
```

### 2. Secret Manager에 시크릿 저장

API 키들을 Secret Manager에 안전하게 저장합니다:

```bash
# OpenAI API 키
echo -n "your-openai-api-key" | gcloud secrets create OPENAI_API_KEY --data-file=-

# DART API 키
echo -n "your-dart-api-key" | gcloud secrets create DART_API_KEY --data-file=-

# Google Spreadsheet ID
echo -n "your-spreadsheet-id" | gcloud secrets create GOOGLE_SPREADSHEET_ID --data-file=-

# Google Credentials JSON (base64 인코딩)
base64 credentials.json | gcloud secrets create GOOGLE_CREDENTIALS_JSON --data-file=-
```

## 📁 배포 구조

```
크롤링/
├── gcp_deploy/
│   ├── Dockerfile              # Docker 이미지 빌드용
│   ├── requirements.txt        # Python 패키지
│   ├── main.py                 # Cloud Run Job 진입점
│   └── run_pipeline.py         # 파이프라인 로직 (복사)
└── GCP_DEPLOYMENT.md           # 이 파일
```

## 🚀 단계별 배포

### 1단계: 배포 디렉토리 및 파일 준비

#### 1.1 디렉토리 생성

```bash
cd 크롤링
mkdir -p gcp_deploy
cd gcp_deploy
```

#### 1.2 Dockerfile 생성

`gcp_deploy/Dockerfile`:

```dockerfile
FROM python:3.11-slim

# 시스템 패키지 설치 (Chrome용)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Chrome 설치
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Chromedriver 설치
RUN CHROMEDRIVER_VERSION=`curl -sS chromedriver.storage.googleapis.com/LATEST_RELEASE` && \
    wget -N http://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip \
    && unzip chromedriver_linux64.zip \
    && rm chromedriver_linux64.zip \
    && mv chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver

# 작업 디렉토리 설정
WORKDIR /app

# Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# Cloud Run Job 실행
CMD ["python", "main.py"]
```

#### 1.3 requirements.txt 복사

```bash
cp ../requirements.txt .
```

#### 1.4 main.py 생성

`gcp_deploy/main.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloud Run Job 진입점
run_pipeline.py를 실행하고 Secret Manager에서 환경 변수 로드
"""

import os
import sys
import json
import base64
from google.cloud import secretmanager

def get_secret(secret_id):
    """Secret Manager에서 시크릿 가져오기"""
    try:
        client = secretmanager.SecretManagerServiceClient()
        project_id = os.environ.get('GCP_PROJECT_ID')
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Secret {secret_id} 가져오기 실패: {e}")
        return None


def setup_environment():
    """환경 변수 설정"""
    # GCP 프로젝트 ID
    project_id = os.environ.get('GCP_PROJECT_ID')
    if not project_id:
        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
    
    os.environ['GCP_PROJECT_ID'] = project_id
    
    # Secret Manager에서 시크릿 가져오기
    secrets = {
        'OPENAI_API_KEY': get_secret('OPENAI_API_KEY'),
        'DART_API_KEY': get_secret('DART_API_KEY'),
        'GOOGLE_SPREADSHEET_ID': get_secret('GOOGLE_SPREADSHEET_ID'),
    }
    
    # Google Credentials JSON 처리
    creds_json_b64 = get_secret('GOOGLE_CREDENTIALS_JSON')
    if creds_json_b64:
        creds_json = base64.b64decode(creds_json_b64).decode('utf-8')
        # 임시 파일로 저장
        with open('/tmp/credentials.json', 'w') as f:
            f.write(creds_json)
        os.environ['GOOGLE_CREDENTIALS_FILE'] = '/tmp/credentials.json'
    
    # 환경 변수 설정
    for key, value in secrets.items():
        if value:
            os.environ[key] = value
    
    # 기본값 설정
    if not os.environ.get('GOOGLE_INPUT_WORKSHEET'):
        os.environ['GOOGLE_INPUT_WORKSHEET'] = '경쟁사 동향 분석'
    if not os.environ.get('GOOGLE_OUTPUT_WORKSHEET'):
        os.environ['GOOGLE_OUTPUT_WORKSHEET'] = '경쟁사 협업 기업 리스트'
    if not os.environ.get('GOOGLE_DART_OUTPUT_WORKSHEET'):
        os.environ['GOOGLE_DART_OUTPUT_WORKSHEET'] = '경쟁사 협업 기업 리스트_with_dart'
    if not os.environ.get('GOOGLE_UNMATCHED_WORKSHEET'):
        os.environ['GOOGLE_UNMATCHED_WORKSHEET'] = '매핑실패기업리스트'
    if not os.environ.get('GOOGLE_CRAWL_WORKSHEET'):
        os.environ['GOOGLE_CRAWL_WORKSHEET'] = '경쟁사 동향 분석'


def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("GCP Cloud Run Job 시작")
    print("=" * 60)
    
    # 환경 변수 설정
    setup_environment()
    
    # run_pipeline 모듈 import 및 실행
    try:
        # 현재 디렉토리를 경로에 추가
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        # run_pipeline 실행
        from run_pipeline import run_pipeline
        run_pipeline()
        
        print("=" * 60)
        print("Cloud Run Job 완료")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

#### 1.5 run_pipeline.py 및 관련 파일 복사

필요한 파일들을 복사합니다:

```bash
# 파이프라인 파일들 복사
cp ../run_pipeline.py .
cp ../google_crawler_togooglesheet.py .
cp ../competitor_llm.py .
cp ../dart_mapping.py .
```

**주의**: 각 파일에서 `.env` 파일 로딩 부분을 Secret Manager에서 가져오도록 수정하거나, `main.py`에서 환경 변수를 미리 설정해야 합니다.

### 2단계: Docker 이미지 빌드 및 푸시

```bash
# 지역 설정
export REGION="asia-northeast3"  # 서울 리전
export IMAGE_NAME="crawler-pipeline"
export IMAGE_TAG="latest"

# Artifact Registry 리포지토리 생성 (처음 한 번만)
gcloud artifacts repositories create crawler-repo \
    --repository-format=docker \
    --location=$REGION \
    --description="Crawler pipeline Docker repository"

# Docker 인증
gcloud auth configure-docker $REGION-docker.pkg.dev

# 이미지 빌드 및 푸시
docker build -t $REGION-docker.pkg.dev/$GCP_PROJECT_ID/crawler-repo/$IMAGE_NAME:$IMAGE_TAG .
docker push $REGION-docker.pkg.dev/$GCP_PROJECT_ID/crawler-repo/$IMAGE_NAME:$IMAGE_TAG
```

### 3단계: Cloud Run Job 생성

```bash
# Job 생성
gcloud run jobs create crawler-pipeline-job \
    --image=$REGION-docker.pkg.dev/$GCP_PROJECT_ID/crawler-repo/$IMAGE_NAME:$IMAGE_TAG \
    --region=$REGION \
    --max-retries=1 \
    --task-timeout=3600 \
    --memory=2Gi \
    --cpu=2 \
    --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID" \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,DART_API_KEY=DART_API_KEY:latest,GOOGLE_SPREADSHEET_ID=GOOGLE_SPREADSHEET_ID:latest,GOOGLE_CREDENTIALS_JSON=GOOGLE_CREDENTIALS_JSON:latest"
```

**옵션 설명:**
- `--max-retries=1`: 실패 시 1회 재시도
- `--task-timeout=3600`: 최대 실행 시간 1시간 (필요시 조정)
- `--memory=2Gi`: 메모리 2GB (Selenium 사용 고려)
- `--cpu=2`: CPU 2개

### 4단계: 테스트 실행

```bash
# 수동 실행 (테스트용)
gcloud run jobs execute crawler-pipeline-job --region=$REGION

# 실행 상태 확인
gcloud run jobs executions list --job=crawler-pipeline-job --region=$REGION

# 로그 확인
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" --limit=50 --format=json
```

## ⏰ 스케줄링 설정

### Cloud Scheduler로 주기적 실행 설정

```bash
# Service Account 생성 (처음 한 번만)
gcloud iam service-accounts create cloud-scheduler-sa \
    --display-name="Cloud Scheduler Service Account"

# Cloud Run Invoker 권한 부여
gcloud run jobs add-iam-policy-binding crawler-pipeline-job \
    --region=$REGION \
    --member="serviceAccount:cloud-scheduler-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/run.invoker"

# Cloud Scheduler 작업 생성
gcloud scheduler jobs create http crawler-pipeline-schedule \
    --location=$REGION \
    --schedule="0 9 * * 1" \
    --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT_ID/jobs/crawler-pipeline-job:run" \
    --http-method=POST \
    --oauth-service-account-email="cloud-scheduler-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --time-zone="Asia/Seoul"
```

**스케줄 형식:**
- `0 9 * * 1`: 매주 월요일 오전 9시
- `0 6 * * *`: 매일 오전 6시
- `0 14 * * 3`: 매주 수요일 오후 2시

### 스케줄 확인 및 관리

```bash
# 스케줄 목록 확인
gcloud scheduler jobs list --location=$REGION

# 스케줄 상세 정보
gcloud scheduler jobs describe crawler-pipeline-schedule --location=$REGION

# 스케줄 수정
gcloud scheduler jobs update http crawler-pipeline-schedule \
    --location=$REGION \
    --schedule="0 10 * * 1"

# 스케줄 삭제
gcloud scheduler jobs delete crawler-pipeline-schedule --location=$REGION
```

## 📊 모니터링

### 로그 확인

```bash
# 실시간 로그 스트리밍
gcloud logging tail "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job"

# 최근 실행 로그
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" \
    --limit=100 \
    --format=json \
    --order=desc
```

### 실행 이력 확인

```bash
# 실행 목록
gcloud run jobs executions list --job=crawler-pipeline-job --region=$REGION

# 특정 실행 상세 정보
gcloud run jobs executions describe EXECUTION_NAME --region=$REGION
```

### GCP Console에서 확인

1. **Cloud Run Jobs**: https://console.cloud.google.com/run/jobs
2. **Cloud Scheduler**: https://console.cloud.google.com/cloudscheduler
3. **Cloud Logging**: https://console.cloud.google.com/logs

## 💰 비용 추정

### 예상 비용 (매주 1회 실행 기준)

**Cloud Run Jobs:**
- 실행 시간: 약 30분 가정
- 메모리: 2GB
- CPU: 2개
- 예상 비용: 약 $0.10 - $0.30/회 (Always Free 티어 범위 내 가능)

**Cloud Scheduler:**
- 작업 3개까지 무료
- 추가 작업: $0.10/월

**Secret Manager:**
- 시크릿 접근: 매월 처음 10,000회 무료
- 이후: $0.06/10,000회

**네트워크:**
- Egress 데이터 전송 비용 (작은 양)

**총 예상 비용:** 
- Always Free 티어 내에서 대부분 가능
- 월 약 $0 - $1 수준 (데이터 전송량에 따라 다름)

### 비용 최적화 팁

1. **메모리/CPU 조정**: 실제 필요량에 맞춰 조정
2. **실행 시간 최적화**: 불필요한 대기 시간 제거
3. **로그 보관 기간**: Cloud Logging 보관 기간 단축

## 🔧 업데이트 및 배포

### 코드 수정 후 재배포

```bash
cd gcp_deploy

# 이미지 재빌드 및 푸시
docker build -t $REGION-docker.pkg.dev/$GCP_PROJECT_ID/crawler-repo/$IMAGE_NAME:$IMAGE_TAG .
docker push $REGION-docker.pkg.dev/$GCP_PROJECT_ID/crawler-repo/$IMAGE_NAME:$IMAGE_TAG

# Job 업데이트 (이미지만 업데이트)
gcloud run jobs update crawler-pipeline-job \
    --image=$REGION-docker.pkg.dev/$GCP_PROJECT_ID/crawler-repo/$IMAGE_NAME:$IMAGE_TAG \
    --region=$REGION
```

## 🛠️ 문제 해결

### 일반적인 오류

1. **Secret Manager 접근 권한 오류**
   ```bash
   # Cloud Run Job에 Secret Manager 접근 권한 부여
   gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
       --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
       --role="roles/secretmanager.secretAccessor"
   ```

2. **Chrome 실행 오류**
   - Dockerfile에서 Chrome 설치 확인
   - `--no-sandbox` 옵션 확인 (필요시 추가)

3. **타임아웃 오류**
   - `--task-timeout` 값 증가
   - 데이터량이 많으면 처리 시간 단축 고려

### 디버깅

```bash
# 로컬에서 Docker 이미지 테스트
docker build -t test-crawler .
docker run --rm -it test-crawler

# Cloud Run Job 로그 확인
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job AND severity>=ERROR" --limit=50
```

## 📝 참고사항

- 첫 배포 시 Secret Manager에 시크릿을 미리 생성해야 합니다
- Docker 이미지 크기를 줄이면 빌드 및 배포 시간이 단축됩니다
- Cloud Run Jobs는 실행 시간이 긴 배치 작업에 적합합니다
- 주기적 실행은 Cloud Scheduler와 함께 사용하는 것이 권장됩니다
