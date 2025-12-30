# 배포 단계별 가이드

## 코드 수정 후 배포 과정

코드를 수정한 후 서버에 배포하려면 다음 단계를 따르세요:

### 1단계: 로컬 코드 수정

```bash
# 크롤링_async/ 폴더에서 코드 수정
cd 크롤링/크롤링_async
# 파일 수정 (competitor_llm.py, dart_mapping.py, google_crawler_togooglesheet.py 등)
```

### 2단계: 배포 파일 준비 (setup.sh)

```bash
# gcp_deploy_async 폴더로 이동
cd ../gcp_deploy_async

# 최신 코드 복사 (크롤링_async → gcp_deploy_async)
./setup.sh
```

**setup.sh가 하는 일:**
- `크롤링_async/` 폴더에서 최신 코드 파일들을 `gcp_deploy_async/`로 복사
- 복사되는 파일들:
  - `run_pipeline.py`
  - `google_crawler_togooglesheet.py`
  - `competitor_llm.py`
  - `dart_mapping.py`

### 3단계: 배포 실행 (deploy.sh)

```bash
# Docker 이미지 빌드 및 Cloud Run Job 업데이트
./deploy.sh
```

**deploy.sh가 하는 일:**
1. 필요한 GCP API 활성화 확인
2. Artifact Registry 리포지토리 확인/생성
3. Docker 이미지 빌드 및 푸시
4. Secret Manager 확인
5. Cloud Run Job 업데이트
6. Cloud Scheduler 설정

---

## 전체 명령어 요약

```bash
# 1. 코드 수정 후
cd 크롤링/gcp_deploy_async

# 2. 최신 코드 복사
./setup.sh

# 3. 배포
./deploy.sh
```

---

## 주의사항

1. **Secret Manager**: API 키 등은 한 번만 설정하면 됩니다 (코드 수정 시 재설정 불필요)
2. **첫 배포**: Secret Manager에 시크릿이 없으면 `deploy.sh` 실행 전에 설정해야 함 (SECRET_SETUP.md 참고)
3. **배포 시간**: Docker 이미지 빌드 및 푸시에 5-10분 정도 소요될 수 있습니다

---

## 빠른 배포 (코드 수정 후)

```bash
cd 크롤링/gcp_deploy_async
./setup.sh && ./deploy.sh
```

---

## 배포 확인

```bash
# Cloud Run Job 상태 확인
gcloud run jobs list --region=asia-northeast3

# 최근 실행 기록 확인
gcloud run jobs executions list --job=crawler-pipeline-job-async --region=asia-northeast3 --limit=5

# 로그 확인
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job-async" --limit=50
```




