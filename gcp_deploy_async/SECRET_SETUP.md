# Secret Manager 시크릿 저장 가이드

## 필요한 시크릿 목록

1. **OPENAI_API_KEY** - OpenAI API 키
2. **DART_API_KEY** - DART API 키
3. **GOOGLE_SPREADSHEET_ID** - Google Sheets 스프레드시트 ID
4. **GOOGLE_CREDENTIALS_JSON** - Google 인증 JSON 파일 (base64 인코딩)

## 저장 방법

### 1. GCP 프로젝트 설정

```bash
# 프로젝트 ID 설정 (필요한 경우)
export GCP_PROJECT_ID="crmcrawling"  # 또는 본인의 프로젝트 ID

# 프로젝트 확인
gcloud config set project $GCP_PROJECT_ID
```

### 2. Secret Manager API 활성화

```bash
gcloud services enable secretmanager.googleapis.com
```

### 3. 시크릿 저장

#### 3-1. OpenAI API 키

```bash
echo -n "sk-your-openai-api-key-here" | gcloud secrets create OPENAI_API_KEY --data-file=-
```

#### 3-2. DART API 키

```bash
echo -n "your-dart-api-key-here" | gcloud secrets create DART_API_KEY --data-file=-
```

#### 3-3. Google Spreadsheet ID

```bash
echo -n "1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8" | gcloud secrets create GOOGLE_SPREADSHEET_ID --data-file=-
```

#### 3-4. Google Credentials JSON

```bash
# credentials.json 파일이 있는 경로로 이동 후
base64 credentials.json | gcloud secrets create GOOGLE_CREDENTIALS_JSON --data-file=-
```

또는 파일 경로를 직접 지정:

```bash
base64 /path/to/credentials.json | gcloud secrets create GOOGLE_CREDENTIALS_JSON --data-file=-
```

### 4. 시크릿 확인

```bash
# 모든 시크릿 목록 확인
gcloud secrets list

# 특정 시크릿 정보 확인
gcloud secrets describe OPENAI_API_KEY
gcloud secrets describe DART_API_KEY
gcloud secrets describe GOOGLE_SPREADSHEET_ID
gcloud secrets describe GOOGLE_CREDENTIALS_JSON
```

### 5. 시크릿 값 확인 (필요한 경우)

```bash
# 시크릿 값 읽기 (주의: 실제 키 값이 출력됨)
gcloud secrets versions access latest --secret="OPENAI_API_KEY"
```

## 시크릿 업데이트 (이미 생성된 경우)

시크릿이 이미 존재하는 경우, 새 버전을 추가하여 업데이트할 수 있습니다:

```bash
# OpenAI API 키 업데이트
echo -n "sk-new-api-key" | gcloud secrets versions add OPENAI_API_KEY --data-file=-

# DART API 키 업데이트
echo -n "new-dart-key" | gcloud secrets versions add DART_API_KEY --data-file=-

# Google Spreadsheet ID 업데이트
echo -n "new-spreadsheet-id" | gcloud secrets versions add GOOGLE_SPREADSHEET_ID --data-file=-

# Google Credentials JSON 업데이트
base64 credentials.json | gcloud secrets versions add GOOGLE_CREDENTIALS_JSON --data-file=-
```

## 주의사항

1. **API 키 값 앞뒤 공백 확인**: `echo -n`을 사용하여 개행 문자 제거
2. **credentials.json 경로**: 현재 디렉토리에 있거나 전체 경로 지정
3. **기존 시크릿 확인**: `gcloud secrets list`로 이미 존재하는지 확인
4. **권한 확인**: Secret Manager 권한이 있는 계정으로 실행해야 함

## 문제 해결

### 시크릿이 이미 존재하는 경우

```bash
# 오류: "already exists"
# 해결: 업데이트 명령어 사용 (위의 "시크릿 업데이트" 참고)
```

### 권한 오류

```bash
# 오류: "Permission denied"
# 해결: 프로젝트 관리자에게 Secret Manager 권한 요청
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="user:YOUR_EMAIL" \
    --role="roles/secretmanager.admin"
```




