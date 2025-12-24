# 팀원 서버 접속 가이드

GCP Cloud Run Jobs에 배포된 크롤링 파이프라인에 팀원이 접속하고 관리하는 방법입니다.

## 📋 목차

1. [필수 준비 사항](#1-필수-준비-사항)
2. [권한 부여 (관리자가 해야 할 일)](#2-권한-부여-관리자가-해야-할-일)
3. [팀원 접속 방법](#3-팀원-접속-방법)
4. [확인 및 관리 방법](#4-확인-및-관리-방법)
5. [자주 하는 작업](#5-자주-하는-작업)

---

## 1. 필수 준비 사항

### 팀원이 해야 할 일

#### 1-1. Google 계정 준비
- GCP에 접속할 수 있는 Google 계정 필요
- 회사 Google Workspace 계정 또는 개인 Gmail 계정 가능

#### 1-2. GCP 프로젝트 정보 확인
- **프로젝트 ID**: `crmcrawling` (또는 관리자에게 확인)
- **리전**: `asia-northeast3` (서울)

#### 1-3. gcloud CLI 설치 (선택사항)

**macOS**:
```bash
# Homebrew 사용
brew install google-cloud-sdk

# 또는 공식 설치 스크립트
curl https://sdk.cloud.google.com | bash
```

**Windows**:
- [공식 설치 프로그램](https://cloud.google.com/sdk/docs/install) 다운로드

**Linux**:
```bash
# Ubuntu/Debian
curl https://sdk.cloud.google.com | bash
```

**설치 확인**:
```bash
gcloud --version
```

---

## 2. 권한 부여 (관리자가 해야 할 일)

배포한 사람(관리자)이 팀원에게 권한을 부여해야 합니다.

### 2-1. 필요한 권한 종류

#### 조회만 필요할 때 (Viewer)
- Job 목록 보기
- 실행 이력 확인
- 로그 확인

#### 실행도 필요할 때 (Developer)
- 위 권한 +
- 수동으로 Job 실행
- 코드 재배포 (선택사항)

### 2-2. 권한 부여 명령어

**관리자가 실행해야 합니다:**

```bash
# 프로젝트 ID 설정
export GCP_PROJECT_ID="crmcrawling"
export TEAMMATE_EMAIL="teammate@example.com"  # 팀원 이메일

# 1. 조회 권한만 부여 (가장 안전)
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="user:$TEAMMATE_EMAIL" \
    --role="roles/run.viewer"

gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="user:$TEAMMATE_EMAIL" \
    --role="roles/cloudscheduler.viewer"

gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="user:$TEAMMATE_EMAIL" \
    --role="roles/logging.viewer"

# 2. 실행 권한도 부여 (Job 실행이 필요한 경우)
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="user:$TEAMMATE_EMAIL" \
    --role="roles/run.developer"

# 3. Secret 접근 권한 (Job 실행 시 필요)
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="user:$TEAMMATE_EMAIL" \
    --role="roles/secretmanager.secretAccessor"
```

### 2-3. 권한 확인 (관리자)

```bash
# 특정 팀원의 권한 확인
gcloud projects get-iam-policy $GCP_PROJECT_ID \
    --flatten="bindings[].members" \
    --filter="bindings.members:user:$TEAMMATE_EMAIL"
```

---

## 3. 팀원 접속 방법

### 3-1. 방법 1: GCP Console (웹 브라우저) - 권장 ⭐

**가장 쉬운 방법입니다!**

#### 단계별 접속 방법

1. **GCP Console 접속**
   ```
   https://console.cloud.google.com
   ```

2. **로그인**
   - Google 계정으로 로그인
   - 관리자가 권한 부여한 계정이어야 함

3. **프로젝트 선택**
   - 상단 프로젝트 선택 메뉴 클릭
   - `crmcrawling` 프로젝트 선택

4. **Cloud Run Jobs 메뉴 이동**
   ```
   Cloud Run → Jobs 메뉴
   또는
   https://console.cloud.google.com/run/jobs?project=crmcrawling
   ```

5. **Job 목록 확인**
   - `crawler-pipeline-job` (일반 버전)
   - `crawler-pipeline-job-async` (비동기 버전)

### 3-2. 방법 2: gcloud CLI (터미널)

#### 인증 설정

```bash
# 1. Google 계정으로 로그인
gcloud auth login

# 브라우저가 열리면 Google 계정 선택 및 로그인

# 2. 프로젝트 설정
gcloud config set project crmcrawling

# 3. 기본 리전 설정 (선택사항)
gcloud config set run/region asia-northeast3

# 4. 인증 확인
gcloud auth list
```

#### 연결 테스트

```bash
# Job 목록 확인 (권한 테스트)
gcloud run jobs list --region=asia-northeast3
```

**성공하면** 접속 가능한 것입니다! ✅

---

## 4. 확인 및 관리 방법

### 4-1. GCP Console에서 확인

#### Job 목록 보기
```
Cloud Run → Jobs
```

#### 실행 이력 확인
1. Job 클릭
2. "EXECUTIONS" 탭
3. 각 실행별 상태 확인 (성공/실패)

#### 로그 확인
1. 특정 실행(Execution) 클릭
2. "LOGS" 탭
3. 실시간 로그 확인

### 4-2. gcloud CLI로 확인

#### Job 목록
```bash
gcloud run jobs list --region=asia-northeast3
```

#### 실행 이력
```bash
# 일반 버전
gcloud run jobs executions list \
    --job=crawler-pipeline-job \
    --region=asia-northeast3 \
    --limit=10

# 비동기 버전
gcloud run jobs executions list \
    --job=crawler-pipeline-job-async \
    --region=asia-northeast3 \
    --limit=10
```

#### 최근 실행 상태
```bash
# 최근 실행 정보
gcloud run jobs executions describe LATEST_EXECUTION_NAME \
    --region=asia-northeast3
```

#### 로그 확인
```bash
# 최근 오류 로그
gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job AND severity>=ERROR" \
    --limit=20 \
    --format=json

# 모든 로그
gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" \
    --limit=50
```

---

## 5. 자주 하는 작업

### 5-1. 수동 실행 (권한 필요: run.developer)

#### GCP Console에서
1. Cloud Run → Jobs
2. 실행하려는 Job 선택
3. "EXECUTE" 버튼 클릭
4. 실행 옵션 설정 (필요시)
5. "EXECUTE" 확인

#### gcloud CLI로
```bash
# 일반 버전 실행
gcloud run jobs execute crawler-pipeline-job \
    --region=asia-northeast3

# 비동기 버전 실행
gcloud run jobs execute crawler-pipeline-job-async \
    --region=asia-northeast3
```

### 5-2. 실행 상태 확인

#### 실시간 확인
```bash
# 실행 중인 Job 확인
gcloud run jobs executions list \
    --job=crawler-pipeline-job \
    --region=asia-northeast3 \
    --limit=1
```

#### 실행 완료 대기
```bash
# 실행 완료까지 대기
gcloud run jobs executions describe EXECUTION_NAME \
    --region=asia-northeast3 \
    --format="value(status.conditions[0].type)"
```

### 5-3. 로그 실시간 모니터링

```bash
# 실시간 로그 스트리밍
gcloud logging tail \
    "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" \
    --format=json
```

### 5-4. 스케줄 확인

#### Cloud Scheduler에서
```
Cloud Scheduler 메뉴
또는
https://console.cloud.google.com/cloudscheduler?project=crmcrawling
```

#### gcloud CLI로
```bash
# 스케줄 목록
gcloud scheduler jobs list \
    --location=asia-northeast3

# 스케줄 상세 정보
gcloud scheduler jobs describe crawler-pipeline-schedule \
    --location=asia-northeast3
```

### 5-5. Google Sheets 확인

**중요**: Google Sheets는 별도로 공유해야 합니다!

1. **시트 접근 권한 확인**
   - Google Sheets URL 확인
   - 시트 소유자가 팀원에게 "편집" 또는 "보기" 권한 부여

2. **시트 URL 예시**
   ```
   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
   ```

3. **시트 공유 방법**
   - 시트 열기 → 우측 상단 "공유" 버튼
   - 팀원 이메일 입력
   - 권한 설정 (편집/보기)

---

## 6. 문제 해결

### 6-1. 권한 오류

**오류 메시지**: `PERMISSION_DENIED`

**해결 방법**:
1. 관리자에게 권한 부여 요청
2. 올바른 프로젝트 선택 확인
3. 올바른 Google 계정으로 로그인 확인

```bash
# 현재 인증된 계정 확인
gcloud auth list

# 프로젝트 확인
gcloud config get-value project
```

### 6-2. Job을 찾을 수 없음

**오류 메시지**: `Job not found`

**해결 방법**:
1. 올바른 리전 확인 (`asia-northeast3`)
2. Job 이름 확인 (일반 버전/비동기 버전 구분)
3. 프로젝트 ID 확인

```bash
# 모든 Job 목록 확인
gcloud run jobs list --region=asia-northeast3
```

### 6-3. 실행 실패

**확인 사항**:
1. 로그 확인 (오류 메시지 확인)
2. Secret Manager 설정 확인 (API 키 등)
3. Google Sheets 권한 확인

```bash
# 최근 실행 로그
gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" \
    --limit=50 \
    --format="table(timestamp, textPayload)"
```

---

## 7. 권한 레벨 요약

| 권한 | 역할 | 할 수 있는 일 |
|------|------|--------------|
| `run.viewer` | 조회만 | Job 목록, 실행 이력, 로그 확인 |
| `run.developer` | 개발자 | 위 권한 + Job 실행, 코드 재배포 |
| `run.admin` | 관리자 | 위 권한 + Job 삭제, 설정 변경 |
| `logging.viewer` | 로그 조회 | 로그 확인 |
| `secretmanager.secretAccessor` | Secret 접근 | Job 실행 시 API 키 등 접근 |

---

## 8. 빠른 참조

### 자주 쓰는 명령어

```bash
# 프로젝트 설정
export GCP_PROJECT_ID="crmcrawling"
gcloud config set project $GCP_PROJECT_ID

# Job 목록
gcloud run jobs list --region=asia-northeast3

# Job 실행
gcloud run jobs execute crawler-pipeline-job --region=asia-northeast3

# 실행 이력
gcloud run jobs executions list --job=crawler-pipeline-job --region=asia-northeast3

# 로그 확인
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" --limit=20
```

### 유용한 링크

- **GCP Console**: https://console.cloud.google.com
- **Cloud Run Jobs**: https://console.cloud.google.com/run/jobs
- **Cloud Logging**: https://console.cloud.google.com/logs
- **Cloud Scheduler**: https://console.cloud.google.com/cloudscheduler
- **IAM 관리**: https://console.cloud.google.com/iam-admin/iam

---

## 9. 보안 주의사항

1. **Secret 정보 공유 금지**
   - API 키, 인증 정보는 절대 코드나 채팅으로 공유하지 말 것
   - Secret Manager에 안전하게 저장됨

2. **권한 최소화 원칙**
   - 필요한 최소 권한만 부여
   - 조회만 필요하면 `viewer` 권한만

3. **계정 관리**
   - 회사 계정 사용 권장
   - 개인 계정 사용 시 퇴사 시 권한 회수 필요

---

**도움이 필요하면 관리자에게 문의하세요!** 🙋‍♂️




