#!/bin/bash
# GCP Cloud Run Jobs 배포 스크립트

set -e

# 설정 변수
PROJECT_ID=${GCP_PROJECT_ID:-"crmcrawling"}
REGION=${GCP_REGION:-"asia-northeast3"}  # 서울 리전
IMAGE_NAME="crawler-pipeline"
IMAGE_TAG="latest"
JOB_NAME="crawler-pipeline-job"
SCHEDULER_JOB_NAME="crawler-pipeline-schedule"

# Cloud Run Job 설정
# 최대 성능 설정 (한달 4회 실행 기준으로 무료 크레딧 내 최적화)
MEMORY="16Gi"
CPU="8"
TIMEOUT="7200"  # 2시간 (7200초) - 필요시 10800(3시간)으로 변경 가능
MAX_RETRIES=0

# 스케줄 설정 (매주 월요일 오전 9시)
SCHEDULE="0 9 * * 1"
TIME_ZONE="Asia/Seoul"

echo "=========================================="
echo "GCP Cloud Run Jobs 배포 스크립트"
echo "=========================================="
echo "프로젝트 ID: $PROJECT_ID"
echo "리전: $REGION"
echo "Job 이름: $JOB_NAME"
echo "=========================================="

# 프로젝트 설정
echo -e "\n[1/6] GCP 프로젝트 설정..."
gcloud config set project $PROJECT_ID

# 필요한 API 활성화
echo -e "\n[2/6] 필요한 API 활성화..."
gcloud services enable run.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    artifactregistry.googleapis.com \
    --quiet

# Artifact Registry 리포지토리 생성
echo -e "\n[3/6] Artifact Registry 리포지토리 확인/생성..."
REPO_NAME="crawler-repo"
if ! gcloud artifacts repositories describe $REPO_NAME --location=$REGION &>/dev/null; then
    echo "리포지토리 생성 중..."
    gcloud artifacts repositories create $REPO_NAME \
        --repository-format=docker \
        --location=$REGION \
        --description="Crawler pipeline Docker repository"
else
    echo "리포지토리 이미 존재합니다."
fi

# Docker 인증
echo -e "\n[4/6] Docker 이미지 빌드 및 푸시..."
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# 현재 디렉토리 확인
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Docker 이미지 빌드 및 푸시
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${IMAGE_TAG}"
echo "이미지 URI: $IMAGE_URI"
docker buildx build --platform linux/amd64 -t $IMAGE_URI --push .

# Secret Manager 확인
echo -e "\n[4.5/6] Secret Manager 확인..."
REQUIRED_SECRETS=("OPENAI_API_KEY" "DART_API_KEY" "GOOGLE_SPREADSHEET_ID" "GOOGLE_CREDENTIALS_JSON")
MISSING_SECRETS=()

for secret in "${REQUIRED_SECRETS[@]}"; do
    if ! gcloud secrets describe $secret --project=$PROJECT_ID &>/dev/null; then
        MISSING_SECRETS+=("$secret")
    fi
done

if [ ${#MISSING_SECRETS[@]} -ne 0 ]; then
    echo "경고: 다음 시크릿이 없습니다:"
    for secret in "${MISSING_SECRETS[@]}"; do
        echo "  - $secret"
    done
    echo ""
    echo "다음 명령어로 시크릿을 생성하세요:"
    echo "  # 텍스트 값:"
    echo "  echo -n 'value' | gcloud secrets create SECRET_NAME --data-file=-"
    echo ""
    echo "  # JSON 파일 (base64 인코딩):"
    echo "  base64 credentials.json | gcloud secrets create GOOGLE_CREDENTIALS_JSON --data-file=-"
    echo ""
    read -p "계속하시겠습니까? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Cloud Run Job 생성/업데이트
echo -e "\n[5/6] Cloud Run Job 생성/업데이트..."

# Service Account 확인
SERVICE_ACCOUNT="run-runtime-sa@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud run jobs deploy $JOB_NAME \
    --image=$IMAGE_URI \
    --region=$REGION \
    --max-retries=$MAX_RETRIES \
    --task-timeout=$TIMEOUT \
    --memory=$MEMORY \
    --cpu=$CPU \
    --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID" \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,DART_API_KEY=DART_API_KEY:latest,GOOGLE_SPREADSHEET_ID=GOOGLE_SPREADSHEET_ID:latest,GOOGLE_CREDENTIALS_JSON=GOOGLE_CREDENTIALS_JSON:latest" \
    --service-account=$SERVICE_ACCOUNT \
    --quiet

# Secret Manager 접근 권한 부여
echo "Secret Manager 접근 권한 확인..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet || echo "권한이 이미 설정되어 있거나 설정에 실패했습니다."

# Cloud Scheduler 설정
echo -e "\n[6/6] Cloud Scheduler 작업 설정..."

# Service Account 생성 (Scheduler용)
SCHEDULER_SA="cloud-scheduler-sa@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe $SCHEDULER_SA &>/dev/null; then
    echo "Service Account 생성 중..."
    gcloud iam service-accounts create cloud-scheduler-sa \
        --display-name="Cloud Scheduler Service Account" \
        --quiet
else
    echo "Service Account가 이미 존재합니다."
fi

# Cloud Run Invoker 권한 부여
gcloud run jobs add-iam-policy-binding $JOB_NAME \
    --region=$REGION \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker" \
    --quiet || echo "권한 설정에 실패했습니다. 수동으로 확인해주세요."

# Cloud Scheduler 작업 생성/업데이트
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

if gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --location=$REGION &>/dev/null; then
    echo "스케줄러 작업 업데이트 중..."
    gcloud scheduler jobs update http $SCHEDULER_JOB_NAME \
        --location=$REGION \
        --schedule="$SCHEDULE" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="${SCHEDULER_SA}" \
        --time-zone="$TIME_ZONE" \
        --quiet
else
    echo "스케줄러 작업 생성 중..."
    gcloud scheduler jobs create http $SCHEDULER_JOB_NAME \
        --location=$REGION \
        --schedule="$SCHEDULE" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="${SCHEDULER_SA}" \
        --time-zone="$TIME_ZONE" \
        --quiet
fi

echo ""
echo "=========================================="
echo "배포 완료!"
echo "=========================================="
echo "Job 이름: $JOB_NAME"
echo "리전: $REGION"
echo "스케줄: $SCHEDULE ($TIME_ZONE)"
echo ""
echo "테스트 실행:"
echo "  gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "실행 상태 확인:"
echo "  gcloud run jobs executions list --job=$JOB_NAME --region=$REGION"
echo ""
echo "로그 확인:"
echo "  gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --limit=50"
echo "=========================================="

