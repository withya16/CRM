# GCP 배포 가이드 - 상세 설명

이 문서는 각 파일의 의미와 배포 자동화 과정을 단계별로 설명합니다.

## 📁 파일 구조 및 역할

```
gcp_deploy/
├── Dockerfile              # 컨테이너 이미지 정의
├── requirements.txt        # Python 패키지 의존성
├── main.py                # Cloud Run Job 진입점 (실제 실행 코드)
├── deploy.sh              # 배포 자동화 스크립트 ⭐
├── setup.sh               # 배포 전 파일 준비 스크립트
├── .dockerignore          # Docker 빌드 시 제외할 파일
└── README.md              # 빠른 시작 가이드
```

## 📄 각 파일의 의미

### 1. Dockerfile

**역할**: 애플리케이션을 실행할 수 있는 컨테이너 이미지를 만드는 "설명서"

**내용**:
- Python 3.11 기반 이미지 사용
- Chrome과 Chromedriver 설치 (Selenium 크롤링용)
- 필요한 Python 패키지 설치
- 애플리케이션 코드 복사
- 실행 명령어 정의

**예시**:
```dockerfile
FROM python:3.11-slim           # 기본 이미지
RUN apt-get install ...         # 시스템 패키지 설치
COPY requirements.txt .         # 파일 복사
RUN pip install ...             # Python 패키지 설치
COPY . .                        # 코드 복사
CMD ["python", "main.py"]       # 실행 명령
```

**왜 필요한가?**: 
- GCP에서 코드를 실행하려면 "어떻게 실행 환경을 만들 것인가"가 필요
- Dockerfile = 실행 환경 구축 방법서

---

### 2. requirements.txt

**역할**: Python 패키지 목록

**내용**:
```
selenium>=4.0.0
beautifulsoup4>=4.11.0
gspread>=5.0.0
google-cloud-secret-manager>=2.0.0
...
```

**왜 필요한가?**: 
- `pip install -r requirements.txt`로 필요한 모든 패키지를 한 번에 설치
- Docker 이미지 빌드 시 자동으로 설치됨

---

### 3. main.py

**역할**: Cloud Run Job이 실행할 실제 코드의 진입점

**주요 기능**:
1. Secret Manager에서 API 키/토큰 가져오기
2. 환경 변수 설정
3. `run_pipeline.py` 실행

**실행 흐름**:
```
Cloud Run Job 시작
    ↓
main.py 실행
    ↓
Secret Manager에서 시크릿 로드
    ↓
환경 변수 설정
    ↓
run_pipeline.py 실행
    ├── google_crawler_togooglesheet.py
    ├── competitor_llm.py
    └── dart_mapping.py
    ↓
완료
```

**왜 필요한가?**: 
- Cloud Run은 `main.py`를 실행함
- Secret Manager 연동 등 GCP 환경에 맞는 초기 설정 수행

---

### 4. deploy.sh ⭐ (배포 자동화 스크립트)

**역할**: 배포 과정을 자동화하는 스크립트

**"배포 자동화"란?**: 
수동으로 여러 명령어를 실행하는 대신, 하나의 스크립트(`./deploy.sh`)를 실행하면 모든 배포 작업이 자동으로 처리되는 것

**수동 작업 (자동화 전)**:
```bash
# 1. API 활성화 (4개 명령어)
gcloud services enable run.googleapis.com
gcloud services enable cloudscheduler.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable artifactregistry.googleapis.com

# 2. 리포지토리 생성 (여러 명령어)
gcloud artifacts repositories create ...

# 3. Docker 빌드 및 푸시 (여러 명령어)
docker build ...
docker push ...

# 4. Cloud Run Job 생성 (복잡한 명령어)
gcloud run jobs deploy ...

# 5. 권한 설정 (여러 명령어)
gcloud projects add-iam-policy-binding ...

# 6. Cloud Scheduler 설정 (복잡한 명령어)
gcloud scheduler jobs create ...

# 총 20개 이상의 명령어를 순서대로 실행해야 함!
```

**자동화 후**:
```bash
./deploy.sh
# 끝! 모든 작업이 자동으로 처리됨
```

**deploy.sh가 하는 일**:
1. ✅ 필요한 API 자동 활성화
2. ✅ Artifact Registry 리포지토리 자동 생성
3. ✅ Docker 이미지 자동 빌드 및 푸시
4. ✅ Cloud Run Job 자동 생성/업데이트
5. ✅ 권한 자동 설정
6. ✅ Cloud Scheduler 자동 설정

---

### 5. setup.sh

**역할**: 배포 전에 필요한 파일들을 자동으로 복사

**왜 필요한가?**:
- `gcp_deploy` 폴더에는 배포용 파일만 있고
- 실제 파이프라인 코드(`run_pipeline.py` 등)는 상위 폴더에 있음
- 배포 전에 이 파일들을 복사해야 함

**실행 전**:
```
크롤링/
├── run_pipeline.py          ← 여기에 있음
├── google_crawler_togooglesheet.py
├── competitor_llm.py
├── dart_mapping.py
└── gcp_deploy/
    ├── Dockerfile
    ├── main.py
    └── ... (코드 파일 없음)
```

**setup.sh 실행 후**:
```
gcp_deploy/
├── Dockerfile
├── main.py
├── run_pipeline.py          ← 복사됨!
├── google_crawler_togooglesheet.py  ← 복사됨!
├── competitor_llm.py        ← 복사됨!
└── dart_mapping.py          ← 복사됨!
```

---

## 🔄 전체 배포 과정 (자동화 흐름)

### 단계별 상세 설명

#### **1단계: 사전 준비**

```bash
# GCP 프로젝트 설정
export GCP_PROJECT_ID="your-project-id"
export GCP_REGION="asia-northeast3"

# GCP 로그인
gcloud auth login
gcloud config set project $GCP_PROJECT_ID
```

**목적**: 
- GCP에 접근할 수 있는 권한 획득
- 작업할 프로젝트 지정

---

#### **2단계: Secret Manager에 시크릿 저장**

```bash
# OpenAI API 키
echo -n "sk-..." | gcloud secrets create OPENAI_API_KEY --data-file=-

# DART API 키
echo -n "your-key" | gcloud secrets create DART_API_KEY --data-file=-

# Google Spreadsheet ID
echo -n "1oYJqCNp..." | gcloud secrets create GOOGLE_SPREADSHEET_ID --data-file=-

# Google Credentials JSON (base64 인코딩)
base64 credentials.json | gcloud secrets create GOOGLE_CREDENTIALS_JSON --data-file=-
```

**목적**: 
- API 키를 안전하게 저장 (코드에 노출되지 않음)
- Cloud Run Job이 실행 시 Secret Manager에서 자동으로 가져옴

**왜 필요한가?**: 
- 코드에 API 키를 직접 쓰면 보안 위험
- Secret Manager = 암호화된 저장소

---

#### **3단계: 파일 준비**

```bash
cd gcp_deploy
./setup.sh
```

**실행 내용**:
- `run_pipeline.py` 복사
- `google_crawler_togooglesheet.py` 복사
- `competitor_llm.py` 복사
- `dart_mapping.py` 복사

**왜 필요한가?**: 
- Docker 이미지 빌드 시 이 파일들이 필요
- Dockerfile의 `COPY . .` 명령이 이 파일들을 이미지에 포함시킴

---

#### **4단계: 배포 자동화 스크립트 실행** ⭐

```bash
./deploy.sh
```

이 스크립트가 **자동으로** 다음 작업들을 순차적으로 수행합니다:

##### **4-1. API 활성화**

```bash
gcloud services enable run.googleapis.com
gcloud services enable cloudscheduler.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable artifactregistry.googleapis.com
```

**목적**: 
- Cloud Run, Scheduler, Secret Manager, Artifact Registry 기능 활성화
- 처음 한 번만 실행하면 됨

---

##### **4-2. Artifact Registry 리포지토리 생성**

```bash
# 리포지토리가 없으면 생성
gcloud artifacts repositories create crawler-repo \
    --repository-format=docker \
    --location=asia-northeast3
```

**목적**: 
- Docker 이미지를 저장할 저장소 생성
- GCP의 Docker 이미지 저장소 = Artifact Registry

**비유**: 
- Docker Hub 같은 곳인데, GCP 전용 버전

---

##### **4-3. Docker 이미지 빌드 및 푸시**

```bash
# Docker 인증
gcloud auth configure-docker asia-northeast3-docker.pkg.dev

# 이미지 빌드
docker build -t asia-northeast3-docker.pkg.dev/프로젝트ID/crawler-repo/crawler-pipeline:latest .

# 이미지 푸시
docker push asia-northeast3-docker.pkg.dev/프로젝트ID/crawler-repo/crawler-pipeline:latest
```

**목적**: 
1. **빌드**: Dockerfile을 읽어서 실행 가능한 이미지 생성
   - Python, Chrome, 코드 등이 모두 포함된 "패키지" 생성
2. **푸시**: 생성한 이미지를 Artifact Registry에 업로드
   - GCP에서 이 이미지를 사용할 수 있게 함

**비유**: 
- 빌드 = 상자를 포장하는 것
- 푸시 = 포장한 상자를 창고(Artifact Registry)에 보관하는 것

---

##### **4-4. Cloud Run Job 생성/업데이트**

```bash
gcloud run jobs deploy crawler-pipeline-job \
    --image=asia-northeast3-docker.pkg.dev/프로젝트ID/crawler-repo/crawler-pipeline:latest \
    --region=asia-northeast3 \
    --memory=2Gi \
    --cpu=2 \
    --task-timeout=3600 \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,..."
```

**목적**: 
- 실행할 Job 정의
- 어떤 이미지를 사용할지, 얼마나 메모리를 쓸지, Secret은 어떻게 가져올지 설정

**설정 내용**:
- `--memory=2Gi`: 메모리 2GB 할당
- `--cpu=2`: CPU 2개 할당
- `--task-timeout=3600`: 최대 1시간 동안 실행 가능
- `--set-secrets`: Secret Manager에서 시크릿 자동 로드

**비유**: 
- Cloud Run Job = "이미지를 실행하는 방법"을 정의한 명령서

---

##### **4-5. 권한 설정**

```bash
# Cloud Run Service Account에 Secret Manager 접근 권한 부여
gcloud projects add-iam-policy-binding 프로젝트ID \
    --member="serviceAccount:프로젝트ID@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

**목적**: 
- Cloud Run Job이 Secret Manager에서 시크릿을 읽을 수 있도록 권한 부여
- 없으면 "권한 없음" 오류 발생

---

##### **4-6. Cloud Scheduler 설정**

```bash
# Service Account 생성
gcloud iam service-accounts create cloud-scheduler-sa

# Cloud Run Invoker 권한 부여
gcloud run jobs add-iam-policy-binding crawler-pipeline-job \
    --member="serviceAccount:cloud-scheduler-sa@프로젝트ID.iam.gserviceaccount.com" \
    --role="roles/run.invoker"

# 스케줄러 작업 생성
gcloud scheduler jobs create http crawler-pipeline-schedule \
    --schedule="0 9 * * 1" \
    --uri="https://asia-northeast3-run.googleapis.com/.../crawler-pipeline-job:run" \
    --http-method=POST
```

**목적**: 
- 매주 월요일 오전 9시에 자동으로 Cloud Run Job 실행
- Cloud Scheduler = "크론 작업"을 관리하는 GCP 서비스

**스케줄 형식**: `0 9 * * 1`
- `0`: 분 (0분)
- `9`: 시 (9시)
- `*`: 일 (매일)
- `*`: 월 (매월)
- `1`: 요일 (월요일, 0=일요일)

---

## 🎯 전체 흐름 요약

```
[사용자]
    ↓
1. ./setup.sh 실행
    → 파일 복사 (run_pipeline.py 등)
    ↓
2. Secret Manager에 시크릿 저장 (수동 1회)
    → API 키, 토큰 저장
    ↓
3. ./deploy.sh 실행
    ├── API 활성화
    ├── 리포지토리 생성
    ├── Docker 이미지 빌드 및 푸시
    ├── Cloud Run Job 생성
    ├── 권한 설정
    └── Cloud Scheduler 설정
    ↓
[배포 완료]
    ↓
[Cloud Scheduler] (매주 월요일 오전 9시)
    ↓
[Cloud Run Job 실행]
    ├── Secret Manager에서 시크릿 로드
    ├── main.py 실행
    └── run_pipeline.py 실행
        ├── 크롤링
        ├── LLM 분석
        └── DART 매핑
    ↓
[Google Sheets에 결과 저장]
```

## 💡 배포 자동화의 장점

### 자동화 전 (수동 작업)

1. ❌ 명령어 20개 이상을 순서대로 실행해야 함
2. ❌ 실수로 순서를 바꾸면 오류 발생
3. ❌ 설정값을 매번 입력해야 함
4. ❌ 오류 발생 시 어디서 실패했는지 찾기 어려움
5. ❌ 다른 사람이 배포하기 어려움

### 자동화 후

1. ✅ 하나의 명령어(`./deploy.sh`)로 모든 작업 완료
2. ✅ 순서가 보장됨 (스크립트에 정의됨)
3. ✅ 환경 변수로 설정 관리 (한 번 설정하면 계속 사용)
4. ✅ 오류 발생 시 스크립트가 중단되어 원인 파악 용이
5. ✅ 다른 사람도 같은 명령어로 쉽게 배포 가능

## 🔍 각 단계 확인 방법

### Secret Manager 확인

```bash
# 시크릿 목록 확인
gcloud secrets list

# 특정 시크릿 확인
gcloud secrets describe OPENAI_API_KEY
```

### Docker 이미지 확인

```bash
# Artifact Registry에서 이미지 확인
gcloud artifacts docker images list asia-northeast3-docker.pkg.dev/프로젝트ID/crawler-repo
```

### Cloud Run Job 확인

```bash
# Job 목록
gcloud run jobs list --region=asia-northeast3

# Job 상세 정보
gcloud run jobs describe crawler-pipeline-job --region=asia-northeast3
```

### Cloud Scheduler 확인

```bash
# 스케줄 목록
gcloud scheduler jobs list --location=asia-northeast3

# 스케줄 상세 정보
gcloud scheduler jobs describe crawler-pipeline-schedule --location=asia-northeast3
```

## 🚀 실제 사용 예시

### 첫 배포

```bash
# 1. 환경 설정
export GCP_PROJECT_ID="my-project-123"
export GCP_REGION="asia-northeast3"
gcloud config set project $GCP_PROJECT_ID

# 2. 시크릿 저장 (처음 한 번만)
echo -n "sk-abc123..." | gcloud secrets create OPENAI_API_KEY --data-file=-
echo -n "dart-key" | gcloud secrets create DART_API_KEY --data-file=-
echo -n "1oYJqCNp..." | gcloud secrets create GOOGLE_SPREADSHEET_ID --data-file=-
base64 credentials.json | gcloud secrets create GOOGLE_CREDENTIALS_JSON --data-file=-

# 3. 파일 준비
cd 크롤링/gcp_deploy
./setup.sh

# 4. 배포 (모든 작업 자동 처리!)
./deploy.sh
```

### 코드 수정 후 재배포

```bash
# 코드 수정 후...

# 1. 파일 준비 (수정된 파일 복사)
./setup.sh

# 2. 배포 (이미지만 업데이트됨)
./deploy.sh
```

### 스케줄 변경

```bash
# 매일 오전 6시로 변경
gcloud scheduler jobs update http crawler-pipeline-schedule \
    --location=asia-northeast3 \
    --schedule="0 6 * * *"
```

## 📝 정리

- **Dockerfile**: 컨테이너 이미지 만드는 방법
- **main.py**: Cloud Run Job 실행 코드
- **deploy.sh**: 배포를 자동화하는 스크립트 ⭐
- **setup.sh**: 배포 전 파일 준비 스크립트

**배포 자동화 = 복잡한 작업들을 하나의 명령어로 처리**

---

## 🌐 다른 컴퓨터에서 확인/관리하기

### 배포 후 다른 컴퓨터에서도 확인 가능한가?

**네, 가능합니다!** GCP에 배포하면 **어느 컴퓨터에서든** 다음을 할 수 있습니다:

#### ✅ 가능한 작업들

1. **실행 상태 확인**
   ```bash
   # 어느 컴퓨터에서든 실행 가능 (gcloud CLI만 있으면 됨)
   gcloud run jobs executions list --job=crawler-pipeline-job --region=asia-northeast3
   ```

2. **로그 확인**
   ```bash
   # 실행 로그 확인
   gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" --limit=50
   ```

3. **수동 실행**
   ```bash
   # 스케줄을 기다리지 않고 바로 실행
   gcloud run jobs execute crawler-pipeline-job --region=asia-northeast3
   ```

4. **GCP Console에서 확인**
   - https://console.cloud.google.com/run/jobs (어떤 브라우저에서든 접속 가능)
   - 실행 이력, 로그, 설정 등 모두 확인 가능

5. **데이터 확인 (Google Sheets)**
   - Google Sheets에 접근 가능한 컴퓨터에서만 확인 가능
   - 실행 결과는 Google Sheets에 저장되므로, Google 계정으로 로그인하면 어디서든 확인 가능

6. **코드 수정 및 재배포**
   ```bash
   # 새로운 컴퓨터에서도 가능 (코드와 gcloud CLI만 있으면 됨)
   cd 크롤링/gcp_deploy
   ./setup.sh    # 코드 복사
   ./deploy.sh   # 재배포
   ```

#### 🔑 필요한 것들

**다른 컴퓨터에서 작업하려면:**

1. **GCP CLI 설치**
   ```bash
   # macOS
   brew install google-cloud-sdk
   
   # Linux
   curl https://sdk.cloud.google.com | bash
   
   # Windows
   # 인스톨러 다운로드: https://cloud.google.com/sdk/docs/install
   ```

2. **GCP 인증**
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

3. **코드 저장소 접근**
   - Git 저장소에 코드를 올려두면 어디서든 클론 가능
   - 또는 코드 파일을 USB 등으로 복사

#### 📊 확인 방법별 접근 수준

| 확인 항목 | 필요한 것 | 접근 위치 |
|----------|----------|----------|
| 실행 상태 | gcloud CLI 또는 GCP Console | 어디서든 가능 |
| 실행 로그 | gcloud CLI 또는 GCP Console | 어디서든 가능 |
| 실행 결과 데이터 | Google Sheets 접근 권한 | Google 계정만 있으면 어디서든 가능 |
| 코드 수정/재배포 | 코드 + gcloud CLI | 코드와 CLI만 있으면 어디서든 가능 |

#### 🌍 실제 사용 시나리오

**시나리오 1: 집에서 배포, 회사에서 확인**
```bash
# 회사 컴퓨터에서
gcloud auth login  # 한 번만
gcloud run jobs executions list --job=crawler-pipeline-job --region=asia-northeast3
# → 집에서 배포한 Job의 실행 상태 확인 가능!
```

**시나리오 2: 회사에서 배포, 집에서 확인**
```bash
# 집 컴퓨터에서
# Google Sheets 열기 → 데이터 확인 가능
# GCP Console 접속 → 실행 로그 확인 가능
```

**시나리오 3: 노트북에서 코드 수정 후 재배포**
```bash
# 노트북에서
git pull  # 최신 코드 가져오기
cd 크롤링/gcp_deploy
./setup.sh
./deploy.sh
# → 서버 컴퓨터에서 배포한 것과 동일하게 업데이트됨!
```

#### 🔐 보안 주의사항

1. **Secret Manager는 안전함**
   - API 키는 Secret Manager에 저장되므로 코드에 노출되지 않음
   - 다른 컴퓨터에서 코드를 봐도 API 키는 보이지 않음

2. **인증 필요**
   - GCP 작업은 `gcloud auth login` 필요
   - Google Sheets 접근은 Google 계정 로그인 필요

3. **권한 관리**
   - GCP 프로젝트에 접근 권한이 있는 계정만 작업 가능
   - 팀원에게 권한을 부여하려면 IAM 설정 필요

#### 💡 베스트 프랙티스

1. **코드는 Git에 올리기**
   ```bash
   git add .
   git commit -m "GCP 배포 설정 추가"
   git push
   ```
   - 다른 컴퓨터에서 `git clone`으로 쉽게 가져올 수 있음

2. **환경 변수는 .env.example에 예시만 올리기**
   - 실제 `.env`는 `.gitignore`에 포함
   - Secret Manager에 실제 값 저장

3. **문서화**
   - README.md에 배포 방법 정리
   - 팀원들이 같은 방법으로 배포/확인 가능

#### 🎯 결론

**배포는 한 번만 하면, 어느 컴퓨터에서든:**
- ✅ 실행 상태 확인 가능
- ✅ 로그 확인 가능  
- ✅ 수동 실행 가능
- ✅ 코드 수정 후 재배포 가능
- ✅ 실행 결과 데이터 확인 가능 (Google Sheets)

**단, 필요한 것:**
- GCP CLI (gcloud)
- GCP 인증 (gcloud auth login)
- 코드 (Git 저장소 또는 파일 복사)
- Google 계정 (데이터 확인용)

---

## 👥 팀원과 공유하기

### 다른 팀원이 배포된 Job을 볼 수 있나요?

**기본적으로는 안 됩니다.** GCP 프로젝트에 **접근 권한이 있는 팀원만** 볼 수 있습니다.

#### 📋 권한 부여 방법

##### 방법 1: GCP Console에서 권한 부여 (권장)

1. **GCP Console 접속**
   - https://console.cloud.google.com/iam-admin/iam

2. **"역할 부여" 클릭**

3. **팀원의 이메일 추가 및 역할 선택**

**권장 역할:**

| 역할 | 권한 | 용도 |
|------|------|------|
| `Cloud Run Viewer` | 조회만 가능 | 실행 상태, 로그 확인 |
| `Cloud Run Developer` | 조회 + 실행 | 수동 실행 가능 |
| `Cloud Run Admin` | 모든 권한 | 조회, 실행, 수정, 삭제 |
| `Cloud Scheduler Viewer` | 스케줄 조회 | 스케줄 확인 |
| `Cloud Scheduler Admin` | 스케줄 관리 | 스케줄 수정 |

**예시 (읽기 전용 권한):**
- `Cloud Run Viewer`
- `Cloud Scheduler Viewer`
- `Cloud Logging Viewer` (로그 확인용)
- `Secret Manager Secret Accessor` (Secret 접근용, 실행이 필요한 경우)

**예시 (실행 권한):**
- `Cloud Run Developer`
- `Cloud Scheduler Viewer`
- `Secret Manager Secret Accessor`

**예시 (관리 권한):**
- `Cloud Run Admin`
- `Cloud Scheduler Admin`
- `Secret Manager Admin`

##### 방법 2: gcloud CLI로 권한 부여

```bash
# 읽기 전용 권한 (조회만 가능)
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="user:teammate@example.com" \
    --role="roles/run.viewer"

gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="user:teammate@example.com" \
    --role="roles/cloudscheduler.viewer"

gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="user:teammate@example.com" \
    --role="roles/logging.viewer"

# 실행 권한 추가
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="user:teammate@example.com" \
    --role="roles/run.developer"

# Secret 접근 권한 (실행이 필요한 경우)
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="user:teammate@example.com" \
    --role="roles/secretmanager.secretAccessor"
```

#### 🔍 팀원이 확인할 수 있는 것들

**권한이 부여된 팀원은 다음을 확인/실행할 수 있습니다:**

1. **GCP Console에서**
   - Cloud Run Jobs 목록
   - 실행 이력
   - 실행 로그
   - 스케줄 설정

2. **gcloud CLI로**
   ```bash
   # 실행 상태 확인
   gcloud run jobs executions list --job=crawler-pipeline-job --region=asia-northeast3
   
   # 로그 확인
   gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" --limit=50
   
   # 수동 실행 (실행 권한이 있는 경우)
   gcloud run jobs execute crawler-pipeline-job --region=asia-northeast3
   ```

3. **Google Sheets 데이터**
   - Google Sheets에 공유 권한이 있으면 데이터 확인 가능
   - 이는 GCP 권한과 별개

#### ⚠️ 주의사항

1. **Secret Manager 권한**
   - `Secret Manager Secret Accessor` 권한이 없으면 실행 불가
   - Job을 실행하려면 이 권한이 필요

2. **프로젝트 수준 권한 vs 리소스 수준 권한**
   - 프로젝트 전체 권한: 모든 Cloud Run Job에 접근
   - 리소스별 권한: 특정 Job만 접근 (고급 설정)

3. **Google Sheets 공유**
   - GCP 권한과 별도로 Google Sheets도 공유해야 데이터 확인 가능
   - Google Sheets에서 "공유" 버튼으로 팀원 추가

#### 💡 팀원이 해야 할 준비 작업

1. **GCP 계정 설정**
   - Google 계정으로 GCP Console 접속
   - 프로젝트 초대 받기 (또는 권한 부여 받기)

2. **gcloud CLI 설치** (선택사항)
   - CLI로 확인/실행하려면 필요
   - Console만 사용하면 불필요

3. **인증**
   ```bash
   gcloud auth login
   gcloud config set project PROJECT_ID
   ```

#### ✅ 확인 방법

팀원이 권한이 있는지 확인:

```bash
# 현재 사용자의 권한 확인
gcloud projects get-iam-policy PROJECT_ID --flatten="bindings[].members" --filter="bindings.members:user:teammate@example.com"

# Cloud Run Job 목록 확인 (권한 테스트)
gcloud run jobs list --region=asia-northeast3
```

**성공하면** 권한이 있는 것입니다!

#### 🎯 정리

- ✅ **팀원에게 권한 부여하면** 배포된 Job 확인 가능
- ✅ **GCP Console** 또는 **gcloud CLI**로 확인
- ✅ **권한 레벨에 따라** 조회/실행/관리 가능
- ✅ **Google Sheets는 별도로 공유** 필요

---

## 🔧 배포 후 관리 작업

### 배포 후 추가 관리가 필요한가요?

**대부분 자동으로 동작하므로, 관리 작업은 많지 않습니다!**

#### ✅ 자동으로 처리되는 것들

1. **스케줄 실행**: Cloud Scheduler가 자동으로 Job 실행
2. **리소스 관리**: GCP가 자동으로 서버 할당/해제
3. **로그 저장**: 모든 실행 로그가 Cloud Logging에 자동 저장
4. **오류 처리**: 실패 시 자동 재시도 (설정한 횟수만큼)

#### 📋 가끔 필요할 수 있는 관리 작업들

##### 1. 실행 상태 확인 (선택사항)

**언제**: 실행이 잘 되고 있는지 확인하고 싶을 때

**방법**:
```bash
# 최근 실행 이력 확인
gcloud run jobs executions list --job=crawler-pipeline-job --region=asia-northeast3 --limit=10

# GCP Console에서 확인
# https://console.cloud.google.com/run/jobs
```

**빈도**: 주 1회 정도면 충분

---

##### 2. 로그 확인 (문제 발생 시)

**언제**: 
- 실행이 실패했을 때
- 데이터가 제대로 들어오지 않을 때
- 오류가 발생했을 때

**방법**:
```bash
# 최근 오류 로그 확인
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job AND severity>=ERROR" --limit=20

# 모든 로그 확인
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job" --limit=50
```

**빈도**: 문제가 있을 때만

---

##### 3. 코드 수정 후 재배포 (필요 시)

**언제**: 
- 버그 수정
- 기능 추가
- 설정 변경

**방법**:
```bash
cd 크롤링/gcp_deploy
./setup.sh    # 수정된 파일 복사
./deploy.sh   # 재배포 (자동으로 처리됨)
```

**빈도**: 코드를 수정할 때만

---

##### 4. 스케줄 변경 (필요 시)

**언제**: 실행 시간이나 주기를 변경하고 싶을 때

**방법**:
```bash
# 매주 화요일 오전 10시로 변경
gcloud scheduler jobs update http crawler-pipeline-schedule \
    --location=asia-northeast3 \
    --schedule="0 10 * * 2"
```

**빈도**: 거의 없음 (처음 설정 후 거의 변경 안 함)

---

##### 5. 비용 확인 (월 1회 권장)

**언제**: 비용이 예상보다 많이 나왔는지 확인

**방법**:
- GCP Console: https://console.cloud.google.com/billing
- 예상 비용: Always Free 티어 내에서 대부분 무료

**빈도**: 월 1회 정도

---

##### 6. Secret 업데이트 (필요 시)

**언제**: API 키가 변경되었을 때

**방법**:
```bash
# Secret 새 버전 추가
echo -n "new-api-key" | gcloud secrets versions add OPENAI_API_KEY --data-file=-

# 최신 버전으로 자동 사용됨 (코드 수정 불필요)
```

**빈도**: API 키가 변경될 때만 (거의 없음)

---

#### 🎯 관리 작업 요약

| 작업 | 빈도 | 필수 여부 | 소요 시간 |
|------|------|----------|----------|
| 실행 상태 확인 | 주 1회 | 선택 | 1분 |
| 로그 확인 | 문제 발생 시 | 선택 | 2-5분 |
| 코드 수정 후 재배포 | 코드 변경 시 | 선택 | 5분 |
| 스케줄 변경 | 거의 없음 | 선택 | 1분 |
| 비용 확인 | 월 1회 | 권장 | 2분 |
| Secret 업데이트 | API 키 변경 시 | 선택 | 1분 |

**결론**: **거의 관리 불필요!** 평소에는 가끔 상태만 확인하면 됩니다.

---

#### 💡 자동 모니터링 설정 (선택사항)

문제 발생 시 자동으로 알림을 받고 싶다면:

##### Alert 정책 설정

```bash
# Cloud Monitoring Alert 생성
gcloud alpha monitoring policies create \
    --notification-channels=CHANNEL_ID \
    --display-name="Crawler Job 실패 알림" \
    --condition-display-name="Job 실패" \
    --condition-threshold-value=1 \
    --condition-threshold-duration=0s \
    --condition-filter='resource.type="cloud_run_job" AND resource.labels.job_name="crawler-pipeline-job" AND severity="ERROR"'
```

**효과**: 
- Job이 실패하면 자동으로 이메일/슬랙 등으로 알림
- 평소에는 확인할 필요 없음

---

#### 🚨 문제 발생 시 대응 방법

##### 문제 1: Job이 실행되지 않음

**확인 사항**:
```bash
# 스케줄 확인
gcloud scheduler jobs describe crawler-pipeline-schedule --location=asia-northeast3

# 수동 실행 테스트
gcloud run jobs execute crawler-pipeline-job --region=asia-northeast3
```

**해결**: 
- 스케줄이 올바른지 확인
- 수동 실행이 되면 스케줄 문제, 안 되면 Job 문제

---

##### 문제 2: Job이 실패함

**확인 사항**:
```bash
# 오류 로그 확인
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crawler-pipeline-job AND severity>=ERROR" --limit=10
```

**해결**:
- 로그에서 오류 원인 확인
- API 키, 권한, 네트워크 등을 점검

---

##### 문제 3: 데이터가 안 들어옴

**확인 사항**:
- Google Sheets에 데이터가 있는지 확인
- 실행 로그에서 성공/실패 확인

**해결**:
- 실행 로그 확인
- Google Sheets 권한 확인

---

#### 📊 권장 관리 체크리스트

**주간 (5분)**
- [ ] 실행 이력 확인 (최근 1주일)
- [ ] 오류 로그 확인

**월간 (10분)**
- [ ] 비용 확인
- [ ] 전체 실행 통계 확인

**분기 (30분)**
- [ ] 코드 업데이트 확인
- [ ] 설정 최적화 검토

---

#### ✅ 정리

**배포 후 관리 작업:**
- ✅ **대부분 자동화됨** - 특별한 관리 불필요
- ✅ **가끔 확인만** - 주 1회 정도 실행 상태 확인
- ✅ **문제 발생 시만** - 로그 확인 및 대응
- ✅ **코드 수정 시만** - 재배포 (자동화 스크립트로 쉬움)

**"배포하고 잊어버려도 되는" 서버리스의 장점!** 🎉
