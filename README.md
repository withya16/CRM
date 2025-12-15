# 경쟁사 동향 분석 파이프라인

Google News에서 경쟁사 관련 뉴스를 크롤링하고, LLM으로 협업 기업을 분석한 후, DART API로 기업 정보를 매핑하는 자동화 파이프라인입니다.

## 📋 목차

- [시스템 구성](#시스템-구성)
- [파일 구조](#파일-구조)
- [실행 방법](#실행-방법)
- [파이프라인 흐름](#파이프라인-흐름)
- [환경 변수 설정](#환경-변수-설정)
- [주요 기능](#주요-기능)

## 🏗️ 시스템 구성

전체 파이프라인은 3단계로 구성됩니다:

1. **크롤링** (`google_crawler_togooglesheet.py`)
   - Google News에서 최근 1주일 경쟁사 관련 뉴스 크롤링
   - Google Sheets에 저장

2. **LLM 분석** (`competitor_llm.py`)
   - 크롤링된 뉴스에서 경쟁사와 협업하는 기업 추출
   - OpenAI API를 사용하여 파트너십 정보 분석
   - Google Sheets에 저장

3. **DART 매핑** (`dart_mapping.py`)
   - 협업 기업명을 DART API와 매핑하여 기업 코드 획득
   - 정규화된 기업명, 매칭 여부 등 정보 추가
   - Google Sheets에 저장

## 📁 파일 구조

```
크롤링/
├── README.md                          # 이 파일
├── requirements.txt                   # Python 패키지 의존성
├── run_pipeline.py                    # 전체 파이프라인 실행 스크립트 (메인)
├── google_crawler_togooglesheet.py   # 1단계: Google News 크롤링
├── competitor_llm.py                  # 2단계: LLM 협업 기업 분석
├── dart_mapping.py                    # 3단계: DART 기업 매핑
├── .env                               # 환경 변수 설정 파일
└── credentials.json                   # Google Sheets API 인증 파일
```

## 🚀 실행 방법

### 1. 사전 준비

#### 1.1 Python 환경 설정

```bash
# Python 3.11 이상 필요
python3 --version

# 가상환경 생성 및 활성화 (선택사항)
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# 또는
venv\Scripts\activate  # Windows
```

#### 1.2 패키지 설치

```bash
cd 크롤링
pip install -r requirements.txt
```

#### 1.3 Google Sheets API 인증 설정

1. Google Cloud Console에서 프로젝트 생성
2. Google Sheets API와 Google Drive API 활성화
3. 서비스 계정 생성 및 JSON 키 파일 다운로드
4. `credentials.json` 파일을 크롤링 폴더에 저장

#### 1.4 환경 변수 설정

`.env` 파일을 생성하고 다음 내용을 설정하세요:

```env
# Google Sheets 설정
GOOGLE_SPREADSHEET_ID=your_spreadsheet_id_here
GOOGLE_CREDENTIALS_FILE=credentials.json

# Google Sheets 시트 이름
GOOGLE_CRAWL_WORKSHEET=경쟁사 동향 분석
GOOGLE_INPUT_WORKSHEET=경쟁사 동향 분석
GOOGLE_OUTPUT_WORKSHEET=경쟁사 협업 기업 리스트
GOOGLE_DART_OUTPUT_WORKSHEET=경쟁사 협업 기업 리스트_with_dart
GOOGLE_UNMATCHED_WORKSHEET=매핑실패기업리스트

# OpenAI API 설정
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_API_ENDPOINT=https://api.openai.com/v1/chat/completions

# DART API 설정
DART_API_KEY=your_dart_api_key_here
```

### 2. 실행

#### 2.1 전체 파이프라인 실행 (권장)

```bash
python run_pipeline.py
```

이 명령어는 다음 순서로 자동 실행합니다:
1. Google News 크롤링
2. LLM 분석
3. DART 매핑

#### 2.2 개별 실행

각 단계를 개별적으로 실행할 수도 있습니다:

```bash
# 1단계: 크롤링만 실행
python google_crawler_togooglesheet.py

# 2단계: LLM 분석만 실행
python competitor_llm.py

# 3단계: DART 매핑만 실행
python dart_mapping.py
```

## 🔄 파이프라인 흐름

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Google News 크롤링                                        │
│    - 경쟁사별 + 키워드 조합으로 검색                          │
│    - 최근 1주일 기사만 수집                                   │
│    - URL 중복 체크 (기존 기사 제외)                           │
│    → Google Sheets: "경쟁사 동향 분석" 시트에 저장           │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. LLM 분석                                                  │
│    - "경쟁사 동향 분석" 시트에서 데이터 읽기                  │
│    - 이미 처리된 기사 제외 (URL 기준)                         │
│    - OpenAI API로 협업 기업 추출                              │
│    → Google Sheets: "경쟁사 협업 기업 리스트" 시트에 저장     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. DART 매핑                                                 │
│    - "경쟁사 협업 기업 리스트" 시트에서 데이터 읽기            │
│    - 이미 처리된 기사 제외 (제목+URL 기준)                    │
│    - DART API로 기업 코드 매핑                                │
│    - Fuzzy 매칭으로 유사 기업 후보 추천                       │
│    → Google Sheets: "경쟁사 협업 기업 리스트_with_dart" 시트에 저장 │
│    → 매핑 실패 기업: "매핑실패기업리스트" 시트에 저장         │
└─────────────────────────────────────────────────────────────┘
```

## ⚙️ 환경 변수 설정

### 필수 환경 변수

| 변수명 | 설명 | 예시 |
|--------|------|------|
| `GOOGLE_SPREADSHEET_ID` | Google Spreadsheet ID | `1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8` |
| `GOOGLE_CREDENTIALS_FILE` | 인증 JSON 파일 경로 | `credentials.json` |
| `OPENAI_API_KEY` | OpenAI API 키 | `sk-...` |
| `DART_API_KEY` | DART API 키 | `발급받은키` |

### 시트 이름 설정

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `GOOGLE_CRAWL_WORKSHEET` | 크롤링 결과 저장 시트 | `경쟁사 동향 분석` |
| `GOOGLE_INPUT_WORKSHEET` | LLM 분석 입력 시트 | `경쟁사 동향 분석` |
| `GOOGLE_OUTPUT_WORKSHEET` | LLM 분석 출력 시트 | `경쟁사 협업 기업 리스트` |
| `GOOGLE_DART_OUTPUT_WORKSHEET` | DART 매핑 출력 시트 | `경쟁사 협업 기업 리스트_with_dart` |
| `GOOGLE_UNMATCHED_WORKSHEET` | 매핑 실패 기업 시트 | `매핑실패기업리스트` |

## 🎯 주요 기능

### 중복 제거

- **크롤링**: URL 기준으로 중복 체크하여 기존 기사는 제외
- **LLM 분석**: 출력 시트에 이미 있는 URL은 분석하지 않음
- **DART 매핑**: 출력 시트에 이미 있는 제목+URL 조합은 매핑하지 않음

### 데이터 보존

- 모든 시트에서 기존 데이터는 **절대 삭제하지 않음**
- 새로 추가된 데이터만 기존 데이터 아래에 **이어서 추가**

### 경쟁사 및 키워드 설정

`google_crawler_togooglesheet.py` 파일에서 직접 수정:

```python
COMPETITORS = [
    "글루코핏", "파스타", "글루어트", "닥터다이어리", "눔", "다노", "필라이즈",
    "레벨스", "시그노스", "뉴트리센스", "버타", "홈핏", "달램", "파크로쉬리조트",
    "더스테이힐링파크", "청리움", "오색그린야드호텔", "깊은산속옹달샘", "GC케어",
    "뷰핏", "레드밸런스", "SNPE", "헬스맥스"
]

KEYWORDS = ["도입", "협약", "협업", "제휴"]
```

### LLM 분석 설정

`competitor_llm.py` 파일에서 직접 수정:

```python
ARTICLES_PER_CALL = 5  # 한 번에 처리할 기사 수
BATCH_SLEEP_SECONDS = 30  # 배치 간 대기 시간 (초)
COMPETITOR_SLEEP_SECONDS = 10  # 경쟁사 간 대기 시간 (초)
```

## 📊 출력 데이터 형식

### 경쟁사 동향 분석 (크롤링 결과)

| 컬럼명 | 설명 |
|--------|------|
| 경쟁사 | 경쟁사 이름 |
| 경쟁사+키워드 | 검색 쿼리 |
| 제목 | 기사 제목 |
| 본문 | 기사 본문 |
| URL | 기사 URL |

### 경쟁사 협업 기업 리스트 (LLM 분석 결과)

| 컬럼명 | 설명 |
|--------|------|
| 사업명 | 대웅그룹 사업명 |
| 경쟁사 | 경쟁사 이름 |
| 협력사/기관명 | 협업하는 기업/기관명 |
| 협력 유형 | 협업 형태 (예: EAP 도입, 공동 연구 등) |
| 근거 기사 제목 | 해당 협업이 언급된 기사 제목 |
| 근거 기사 URL | 기사 URL |
| 기사 날짜 | 기사 발행일 (YY.MM.DD 형식) |

### 경쟁사 협업 기업 리스트_with_dart (DART 매핑 결과)

위 컬럼에 추가로:

| 컬럼명 | 설명 |
|--------|------|
| norm_partner_name | 정규화된 협력사명 (공백 제거, 대문자) |
| dart_match | DART 매핑 성공 여부 (True/False) |
| dart_corp_name | DART 공식 기업명 (매핑 성공 시) |

### 매핑실패기업리스트

| 컬럼명 | 설명 |
|--------|------|
| 협력사/기관명 | 매핑 실패한 협력사명 |
| dart_candidate_name | Fuzzy 매칭 추천 기업명 |
| dart_candidate_code | 추천 기업의 DART 코드 |
| candidate_score | 매칭 점수 (90 이상 권장) |

## 🔧 문제 해결

### 크롤링이 기사를 못 찾는 경우

- Google News의 HTML 구조가 변경되었을 수 있음
- `google_crawler_togooglesheet.py`의 선택자(selector) 확인 필요

### LLM 분석이 실패하는 경우

- OpenAI API 키 확인
- API 할당량 확인 (Rate Limit)
- 네트워크 연결 확인

### DART 매핑이 안 되는 경우

- DART API 키 확인
- 매핑 실패한 기업은 "매핑실패기업리스트" 시트에서 확인
- candidate_score 90 이상인 후보를 수동으로 검토

## 📝 참고사항

- 크롤링은 Selenium을 사용하므로 Chrome/Chromium이 필요합니다
- LLM API 호출은 비용이 발생할 수 있습니다
- 대량의 데이터 처리 시 시간이 오래 걸릴 수 있습니다
- Google Sheets API 할당량 제한이 있을 수 있습니다
