# GCP Cloud Run Jobs 배포 가이드

크롤링 파이프라인을 GCP Cloud Run Jobs로 배포하는 방법입니다.

## 빠른 시작

### 1. 사전 준비

```bash
# GCP 프로젝트 ID 설정
export GCP_PROJECT_ID="crmcrawlering"
export GCP_REGION="asia-northeast3"  # 서울 리전

# GCP CLI 로그인
gcloud auth login
gcloud config set project $GCP_PROJECT_ID
```

### 2. Secret Manager에 시크릿 저장

```bash
# OpenAI API 키
echo -n "OPENAI_API_KEY=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" | gcloud secrets create OPENAI_API_KEY --data-file=-

# DART API 키
echo -n "a9ed724c8b3b3ee43c5beec9e11ca6ee9f576e08" | gcloud secrets create DART_API_KEY --data-file=-

# Google Spreadsheet ID
echo -n "1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8" | gcloud secrets create GOOGLE_SPREADSHEET_ID --data-file=-

# Google Credentials JSON (base64 인코딩)
base64 ../credentials.json | gcloud secrets create GOOGLE_CREDENTIALS_JSON --data-file=-
```

### 3. 파일 준비

```bash
cd gcp_deploy

# 자동으로 필요한 파일들 복사
./setup.sh
```

또는 수동으로:

```bash
cp ../run_pipeline.py .
cp ../google_crawler_togooglesheet.py .
cp ../competitor_llm.py .
cp ../dart_mapping.py .
```

### 4. 배포 실행

```bash
# 배포 스크립트 실행
./deploy.sh
```

## 배포 스크립트 동작

`deploy.sh` 스크립트는 다음 작업을 수행합니다:

1. **필요한 API 활성화**
   - Cloud Run API
   - Cloud Scheduler API
   - Secret Manager API
   - Artifact Registry API

2. **Artifact Registry 리포지토리 생성**
   - Docker 이미지를 저장할 리포지토리

3. **Docker 이미지 빌드 및 푸시**
   - Dockerfile을 사용하여 이미지 빌드
   - Artifact Registry에 푸시

4. **Secret Manager 확인**
   - 필요한 시크릿이 있는지 확인

5. **Cloud Run Job 생성/업데이트**
   - 메모리: 2GB
   - CPU: 2개
   - 타임아웃: 1시간
   - Secret Manager에서 환경 변수 로드

6. **Cloud Scheduler 설정**
   - 기본: 매주 월요일 오전 9시 실행
   - Cloud Run Job을 트리거하도록 설정

## 스케줄 수정

스케줄을 변경하려면 `deploy.sh`에서 다음 변수를 수정하세요:

```bash
# 매주 월요일 오전 9시
SCHEDULE="0 9 * * 1"

# 매일 오전 6시
SCHEDULE="0 6 * * *"

# 매주 수요일 오후 2시
SCHEDULE="0 14 * * 3"
```

또는 직접 수정:

```bash
gcloud scheduler jobs update http crawler-pipeline-schedule \
    --location=asia-northeast3 \
    --schedule="0 10 * * 1"
```

## 테스트 실행

```bash
# 수동 실행
gcloud run jobs execute crawler-pipeline-job --region=asia-northeast3

# 실행 상태 확인
gcloud run jobs executions list --job=crawler-pipeline-job --region=asia-northeast3

# 로그 확인
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" --limit=50
```

## 파일 구조

```
gcp_deploy/
├── Dockerfile              # Docker 이미지 빌드
├── requirements.txt        # Python 패키지
├── main.py                # Cloud Run Job 진입점
├── deploy.sh              # 배포 스크립트
├── .dockerignore          # Docker 빌드 제외 파일
├── README.md              # 이 파일
│
├── run_pipeline.py        # 파이프라인 실행 (복사 필요)
├── google_crawler_togooglesheet.py  # 크롤링 (복사 필요)
├── competitor_llm.py      # LLM 분석 (복사 필요)
└── dart_mapping.py        # DART 매핑 (복사 필요)
```

## 문제 해결

### Secret Manager 권한 오류

```bash
# Cloud Run Service Account에 권한 부여
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="serviceAccount:${PROJECT_ID}@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

### Docker 빌드 오류

```bash
# Docker가 실행 중인지 확인
docker ps

# GCP 인증 확인
gcloud auth configure-docker asia-northeast3-docker.pkg.dev
```

### 실행 실패

로그를 확인하여 오류 원인 파악:

```bash
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job AND severity>=ERROR" --limit=20
```
