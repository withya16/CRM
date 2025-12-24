# GCP 배포 가이드 (비동기 버전)

이 폴더는 **비동기 처리 버전**을 GCP Cloud Run Jobs에 배포하기 위한 파일들입니다.

## 특징

- **비동기 처리**: `aiohttp`를 사용하여 여러 요청을 동시에 처리
- **성능 개선**: 일반 버전보다 2~5배 빠른 실행 속도
- **차단 방지**: Semaphore로 동시 요청 수 제한 (LLM: 3개, 크롤링: 5개)

## 일반 버전과의 차이

| 항목 | 일반 버전 | 비동기 버전 |
|------|----------|------------|
| Job 이름 | `crawler-pipeline-job` | `crawler-pipeline-job-async` |
| 이미지 이름 | `crawler-pipeline` | `crawler-pipeline-async` |
| 스케줄러 | `crawler-pipeline-schedule` | `crawler-pipeline-schedule-async` |
| 코드 위치 | `크롤링/` | `크롤링/크롤링_async/` |

**두 버전을 동시에 배포할 수 있습니다!** 각각 독립적으로 실행됩니다.

## 빠른 시작

### 1. 파일 준비

```bash
cd /Users/withyou/studywithyou/25-2/CRM/크롤링/gcp_deploy_async
./setup.sh
```

이 스크립트는 `크롤링/크롤링_async/` 폴더에서 비동기 버전 파일들을 복사합니다.

### 2. 환경 변수 설정

```bash
export GCP_PROJECT_ID="crmcrawling"
export GCP_REGION="asia-northeast3"
```

### 3. 배포 실행

```bash
./deploy.sh
```

## Secret Manager 설정

배포 스크립트가 자동으로 확인하지만, 필요시 수동으로 설정할 수 있습니다:

```bash
# OpenAI API 키
echo -n "your-openai-api-key" | gcloud secrets create OPENAI_API_KEY --data-file=-

# DART API 키
echo -n "your-dart-api-key" | gcloud secrets create DART_API_KEY --data-file=-

# Google Spreadsheet ID
echo -n "your-spreadsheet-id" | gcloud secrets create GOOGLE_SPREADSHEET_ID --data-file=-

# Google Credentials JSON (base64 인코딩)
cat credentials.json | base64 | gcloud secrets create GOOGLE_CREDENTIALS_JSON --data-file=-
```

## 실행 확인

### 배포된 Job 확인

```bash
gcloud run jobs list --region=asia-northeast3
```

### 수동 실행

```bash
gcloud run jobs execute crawler-pipeline-job-async --region=asia-northeast3
```

### 로그 확인

```bash
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job-async" \
  --limit=50 \
  --format=json
```

## 성능 비교

일반 버전과 비동기 버전의 성능 비교:

- **기사 본문 크롤링**: 5배 빠름 (100개 기사: 50초 → 10초)
- **LLM API 호출**: 2.5배 빠름 (10개 배치: 5분 → 2분)

*실제 성능은 네트워크 상태에 따라 달라질 수 있습니다.*

## 주의사항

1. **API Rate Limit**: 비동기 처리를 사용하더라도 API 제공자의 Rate Limit을 확인하세요.
2. **동시 요청 수**: `MAX_CONCURRENT_REQUESTS` 값을 조정할 수 있습니다 (코드 내).
3. **메모리 사용량**: 동시 요청 수가 많을수록 메모리 사용량이 증가합니다.

## 일반 버전으로 되돌리기

일반 버전을 배포하려면:

```bash
cd /Users/withyou/studywithyou/25-2/CRM/크롤링/gcp_deploy
./setup.sh
./deploy.sh
```

## 자세한 내용

- [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md): 상세한 배포 가이드
- [../크롤링_async/README.md](../크롤링_async/README.md): 비동기 버전 코드 설명
