#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
경쟁사 뉴스 기반 LLM 분석 스크립트 (비동기 처리 버전)

1) Google Sheets에서 경쟁사 뉴스 데이터 로드
2) 경쟁사별 기사들을 배치로 나눠 LLM 분석하여 파트너십 목록 생성
3) 결과를 Google Sheets에 저장 (기사 제목에서 날짜 추출 포함)

[이번 수정에서 해결하려는 문제]
- 비동기로 여러 요청이 한꺼번에 나가면서 429(Too Many Requests) 연속 발생
- 429 발생 시 즉시 재시도/짧은 sleep만 하면 더 악화되는 문제

[해결 방식]
- RPM(요청/분), TPM(토큰/분) 슬라이딩 윈도우 리미터 도입
- 429 응답의 Retry-After 헤더가 있으면 그 값을 우선 사용
- 없으면 지수 백오프 + 랜덤 지터로 재시도
- 배치 작업을 한꺼번에 gather로 "태스크 폭발"시키지 않고,
  in-flight 제한(작업 큐처럼)으로 점진적으로 실행
"""

# ============================================================================
# 시트 이름 설정 (필요시 여기서 수정)
# ============================================================================
GS_INPUT_WORKSHEET = "[크롤링] 경쟁사 기사 수집"
GS_OUTPUT_WORKSHEET = "[LLM] 경쟁사 협업 기업 분석"

import pandas as pd
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import time
import csv
from io import StringIO
from dotenv import load_dotenv
import re
import asyncio
import aiohttp

import random
from collections import deque

# .env 파일 로드 (현재 디렉토리 또는 상위 디렉토리에서 찾음)
# 1. 현재 스크립트 위치 기준으로 .env 파일 찾기
script_dir = os.path.dirname(os.path.abspath(__file__))
env_paths = [
    os.path.join(script_dir, '.env'),  # 크롤링_async/.env
    os.path.join(script_dir, '..', '.env'),  # 크롤링/.env
    os.path.join(script_dir, '..', '..', '.env'),  # CRM/.env
]

for env_path in env_paths:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"[환경변수] .env 파일 로드: {env_path}", flush=True)
        break
else:
    # .env 파일이 없어도 환경변수는 시스템 환경변수에서 가져올 수 있음
    load_dotenv()  # 기본 동작: 현재 디렉토리와 상위 디렉토리에서 자동으로 찾음
    print("[환경변수] .env 파일을 찾지 못했습니다. 시스템 환경변수를 사용합니다.", flush=True)

API_KEY = os.getenv('OPENAI_API_KEY')
API_ENDPOINT = os.getenv('OPENAI_API_ENDPOINT', 'https://api.openai.com/v1/chat/completions')
GS_CRED_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
GS_SPREADSHEET_ID = os.getenv('GOOGLE_SPREADSHEET_ID', '1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8')
# 시트 이름은 파일 상단에서 설정됨 (GS_INPUT_WORKSHEET, GS_OUTPUT_WORKSHEET)

# LLM 분석 설정
ARTICLES_PER_CALL = 5
MAX_ARTICLE_CONTENT_LENGTH = int(os.getenv("MAX_ARTICLE_CONTENT_LENGTH", "2000"))  # 본문 최대 길이 (문자)

# 비동기 처리 설정
MAX_CONCURRENT_REQUESTS = 2  # 동시 요청 수 (세마포어)
MAX_BATCH_TASKS_IN_FLIGHT = int(os.getenv("MAX_BATCH_TASKS_IN_FLIGHT", str(MAX_CONCURRENT_REQUESTS)))
# ↑ 배치 태스크를 한 경쟁사에서 동시에 “실행 상태”로 유지할 개수(메모리/버스트 방지)

if not API_KEY:
    raise ValueError("OPENAI_API_KEY가 .env 파일에 설정되지 않았습니다. .env.example을 참고하세요.")

# ---------------------------
# Rate Limit 설정
# ---------------------------
# 계정/모델 제한이 다르므로 env로 쉽게 조절
OPENAI_RPM = int(os.getenv("OPENAI_RPM", "10"))          # 요청/분(보수적으로)
OPENAI_TPM = int(os.getenv("OPENAI_TPM", "20000"))       # 토큰/분(보수적으로)
OPENAI_TIMEOUT_SEC = int(os.getenv("OPENAI_TIMEOUT_SEC", "180"))  # LLM 응답 대기(초)

def estimate_tokens(text: str) -> int:
    """토큰 수 러프 추정 (TPM 초과 방지를 위해 chars/3로 안전하게 추정)"""
    if not text:
        return 1
    return max(1, len(text) // 3)

class SlidingWindowLimiter:
    """
    window_seconds 동안 cost 합이 capacity를 넘지 않도록 대기시키는 간단 리미터.
    RPM/TPM 모두 동일 로직으로 사용.
    """
    def __init__(self, capacity: int, window_seconds: int = 60):
        self.capacity = capacity
        self.window = window_seconds
        self.q = deque()  # (timestamp, cost)
        self.lock = asyncio.Lock()

    async def acquire(self, cost: int = 1):
        while True:
            async with self.lock:
                now = time.monotonic()

                # 만료된 항목 제거
                while self.q and (now - self.q[0][0]) >= self.window:
                    self.q.popleft()

                used = sum(c for _, c in self.q)
                if used + cost <= self.capacity:
                    self.q.append((now, cost))
                    return

                # 다음 슬롯이 열릴 때까지 대기
                wait = self.window - (now - self.q[0][0])
                wait = max(0.1, wait)

            await asyncio.sleep(wait)

rpm_limiter = SlidingWindowLimiter(OPENAI_RPM, 60)
tpm_limiter = SlidingWindowLimiter(OPENAI_TPM, 60)

# ---------------------------
# 경쟁사 매핑
# ---------------------------
COMPETITOR_BUSINESS_MAP = {
    "글루코핏": "웰다", "파스타": "웰다", "글루어트": "웰다",
    "글루어트(닥터다이어리)": "웰다", "닥터다이어리": "웰다",
    "눔": "웰다", "다노": "웰다", "필라이즈": "웰다",
    "레벨스": "웰다", "시그노스": "웰다", "뉴트리센스": "웰다", "버타": "웰다", "애니핏플러스": "웰다",
    "홈핏": "코어운동센터",
    "달램": "대웅헬스케어,코어운동센터",
    "파크로쉬리조트": "선마을", "더스테이힐링파크": "선마을",
    "청리움": "선마을", "오색그린야드호텔": "선마을", "깊은산속옹달샘": "선마을",
    "GC케어": "대웅헬스케어,디지털헬스케어",
    "뷰릿": "시셀", "레드밸런스": "시셀", "SNPE": "시셀", "헬스맥스": "대웅헬스케어,디지털헬스케어"
}

def get_google_client():
    """Google Sheets 클라이언트 반환"""
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GS_CRED_FILE, scope)
    return gspread.authorize(creds)

def get_gsheet_data(spreadsheet_id, worksheet_name):
    """Google Sheets 데이터를 Pandas DataFrame으로 로드 (status 컬럼 기반 필터링)"""
    try:
        client = get_google_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        
        # get_all_values()를 사용하여 실제 행 번호 추적
        all_values = worksheet.get_all_values()
        if len(all_values) <= 1:
            return None, None
        
        headers = all_values[0]
        data_rows = all_values[1:]
        
        # DataFrame 생성
        df = pd.DataFrame(data_rows, columns=headers)
        
        url_col = None
        for c in df.columns:
            lower = c.lower()
            if lower in ("url", "링크", "기사url", "기사 url"):
                url_col = c
                break

        required_cols = ['경쟁사', '제목', '본문']
        if not all(col in df.columns for col in required_cols):
            print("오류: 데이터에 '경쟁사', '제목', '본문' 컬럼이 부족합니다.", flush=True)
            return None, None

        # status 컬럼이 없으면 생성 (기본값: 빈 문자열)
        if 'status' not in df.columns and 'Status' not in df.columns:
            df['status'] = ''
        else:
            # 대소문자 구분 없이 status 컬럼 찾기
            status_col = None
            for col in df.columns:
                if col.lower() == 'status':
                    status_col = col
                    break
            if status_col and status_col != 'status':
                df['status'] = df[status_col]

        cols = required_cols.copy()
        if url_col:
            cols.append(url_col)
        cols.append('status')
        
        # 실제 시트 행 번호 매핑 (헤더 제외, 2부터 시작, 필터링 전에 추가)
        df['_sheet_row_num'] = range(2, 2 + len(df))
        
        # 본문 길이 필터링
        df = df[df['본문'].astype(str).str.len() > 100].reset_index(drop=True)
        
        # status 필터링: DONE과 SKIP이 아닌 것만 (ERROR, 빈 값만 처리)
        df['status_upper'] = df['status'].astype(str).str.strip().str.upper()
        df = df[~df['status_upper'].isin(['DONE', 'SKIP'])].reset_index(drop=True)
        df = df.drop(columns=['status_upper'], errors='ignore')
        
        # 필요한 컬럼만 선택
        df = df[cols + ['_sheet_row_num']]
        
        return df, worksheet

    except Exception as e:
        print(f"Google Sheets 로드 실패: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return None, None

DATE_PATTERNS = [
    re.compile(r'(\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.)(?:\s|$|[.,])'),
    re.compile(r'(\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.)'),
    re.compile(r'(\d{4}\.\d{1,2}\.\d{1,2}\.)'),
    re.compile(r'(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})(?:\s|$|[.,])'),
    re.compile(r'(\d{4}\.\d{1,2}\.\d{1,2})(?:\s|$|[.,])'),
    re.compile(r'(\d{2}\.\d{1,2}\.\d{1,2})(?:\s|$|[.,]|"|,|$)'),
    re.compile(r'(\d{4}-\d{1,2}-\d{1,2})(?:\s|$|[.,])'),
    re.compile(r'(\d{4}/\d{1,2}/\d{1,2})(?:\s|$|[.,])'),
    re.compile(r'(\d{8})(?:\s|$|[.,])'),
    re.compile(r'(\d{6})(?:\s|$|[.,])'),
]

def normalize_date_to_yy_mm_dd(date_str: str) -> str:
    """다양한 날짜 형식을 YY.MM.DD 형식으로 변환"""
    if not date_str:
        return ""
    date_str = str(date_str).strip()

    date_patterns = [
        (r'(\d{4})[.\s]+(\d{1,2})[.\s]+(\d{1,2})', True),
        (r'(\d{4})-(\d{1,2})-(\d{1,2})', True),
        (r'(\d{4})/(\d{1,2})/(\d{1,2})', True),
        (r'(\d{2})\.(\d{1,2})\.(\d{1,2})', False),
        (r'^(\d{4})(\d{2})(\d{2})$', True),
        (r'^(\d{2})(\d{2})(\d{2})$', False),
        (r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', True),
    ]

    for pattern, has_year in date_patterns:
        m = re.search(pattern, date_str)
        if m:
            if has_year:
                year = m.group(1)
                month = m.group(2)
                day = m.group(3)
                yy = year[-2:] if len(year) == 4 else year
            else:
                yy = m.group(1)
                month = m.group(2)
                day = m.group(3)
            return f"{yy}.{int(month):02d}.{int(day):02d}"

    return date_str

def extract_date_from_title(title: str):
    """제목 끝에서 날짜를 추출하고, 날짜가 제거된 문자열을 반환"""
    if not isinstance(title, str):
        return None, title

    original_title = title
    search_area = original_title[-500:] if len(original_title) > 500 else original_title

    best_match = None
    best_pos = -1

    for pattern in DATE_PATTERNS:
        matches = list(pattern.finditer(search_area))
        if matches:
            m = matches[-1]
            match_pos = len(original_title) - len(search_area) + m.end()
            if match_pos > best_pos:
                best_match = m
                best_pos = match_pos

    if best_match:
        date_str_full = best_match.group(0)
        date_str_group = best_match.group(1)

        new_title = original_title.replace(date_str_full, "", 1).strip()
        new_title = re.sub(r'[.,\s\[\]\(\)\-–—｜|]+$', '', new_title).strip()

        normalized_date = normalize_date_to_yy_mm_dd(date_str_group)
        return normalized_date, new_title

    return None, original_title

def make_prompt(competitor, data_json, business_name=None):
    """경쟁사별 협력사 추출을 위한 프롬프트 생성"""
    if business_name:
        # 콤마로 구분된 여러 사업명 처리
        if ',' in business_name:
            business_list = [b.strip() for b in business_name.split(',')]
            business_items = ', '.join([f"'{b}'" for b in business_list])
            business_text = f"대웅그룹의 **{business_items}** 사업과 직접적으로 연관된 경쟁사입니다."
            business_hint = f"CSV의 '사업명' 컬럼에는 모든 행에서 정확히 **'{business_name}'** (콤마 포함, 그대로)을 사용하세요. 사업명을 분리하거나 변경하지 마세요."
        else:
            business_text = f"대웅그룹의 **'{business_name}'** 사업과 직접적으로 연관된 경쟁사입니다."
            business_hint = f"CSV의 '사업명' 컬럼에는 모든 행에서 **'{business_name}'**을 그대로 사용하세요."
    else:
        business_text = "대웅그룹과 연관된 경쟁사입니다."
        business_hint = "사업명이 명확하지 않은 경우, '사업명' 컬럼은 비워 두거나 기사 맥락상 자연스러운 이름을 사용하세요."

    # 특정 경쟁사에 대한 제약사항
    exclusion_rules = ""
    filter_rules = ""
    if competitor == "파스타":
        exclusion_rules = """
**중요 제약사항:**
- 파스타는 카카오헬스케어의 서비스/제품입니다.
- 따라서 파스타의 협력사/기관명에 **"카카오헬스케어"** 또는 **"카카오"**가 포함되면 안 됩니다.
- 이는 모회사-자회사 관계이지 협력 관계가 아닙니다.
"""
        filter_rules = """
**기사 필터링 조건:**
- **반드시** 기사 제목 또는 본문에 다음 키워드 중 하나 이상이 포함된 기사만 분석하세요:
  * "카카오헬스케어"
  * "카카오"
  * "헬스케어"
- 위 키워드가 전혀 없는 기사는 분석하지 마세요.
- 키워드가 포함된 기사만 CSV에 포함시키세요.

**제외 키워드:**
- 기사 제목 또는 본문에 다음 키워드가 포함된 기사는 **절대 분석하지 마세요** (음식 파스타 관련 기사):
  * "더본코리아"
  * "더본"
  * "음식"
  * "레스토랑"
  * "식당"
- 위 키워드가 포함된 기사는 CSV에 포함시키지 마세요.
"""

    prompt = f"""
당신은 **대웅그룹의 경쟁사 동향 분석 전문가**입니다.

여기서 말하는 **"{competitor}"**는 {business_text}
동명의 다른 회사(이름만 같은 다른 기업)와 **절대 혼동하지 마세요.**

아래에 제공된 기사 데이터만을 사용하여 분석해야 하며,
당신이 사전에 알고 있는 일반 지식이나 외부 정보를 사용하여
새로운 사실(파트너십, 회사명, 서비스명 등)을 **추가로 지어내지 마세요.**

반드시 다음 원칙을 지키세요:

1. **기사 본문에 실제로 등장하는 정보만 사용**
2. **'{competitor}'와의 직접적인 관계만 파트너십으로 인정**
3. **대웅 사업 관점 우선**
4. **후원, 투자는 협력사로 인정하지 않음**
   - 후원 관계는 협력사가 아닙니다
   - 투자 관계도 협력사가 아닙니다
   - 실제 비즈니스 협력(제휴, 협약, 공동 개발, 공급 계약 등)만 협력사로 인정
{exclusion_rules}
{filter_rules}
[분석용 기사 데이터(JSON)]
{data_json}

출력: 아래 헤더를 갖는 **순수 CSV 텍스트만** 출력하세요.
헤더: 번호,사업명,경쟁사,협력사/기관명,협력 유형,근거 기사 제목,근거 기사 URL

- 사업명: {business_hint}
- 경쟁사: '{competitor}' 그대로
- 협력사/기관명: 
  * 후원, 투자 관계는 제외
  * '{competitor}'와 실제 비즈니스 협력을 하는 기업/기관만 포함
  * 모회사, 자회사 관계는 제외
- 협력 유형: 구체적인 협력 형태를 명시 (예: 제휴, 협약, 공동 개발, 공급 계약, 서비스 연계 등)
- 근거 기사 URL: JSON에 있으면 그대로, 없으면 빈 칸
"""
    return prompt

# ---------------------------
# LLM 호출
# ---------------------------
async def call_llm_async(session, semaphore, prompt, batch_info, max_retries=6):
    """
    - RPM/TPM 제한 적용
    - 429: Retry-After 우선, 없으면 지수 백오프 + 지터
    - 5xx: 백오프 후 재시도
    """
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    data = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.0
    }

    est_prompt_tokens = estimate_tokens(prompt)
    est_total_tokens = est_prompt_tokens + int(data["max_tokens"])

    for attempt in range(max_retries):
        # ✅ RPM/TPM 제한: 여기서 “스스로 기다리면서” 429를 근본적으로 줄임
        await rpm_limiter.acquire(1)
        await tpm_limiter.acquire(est_total_tokens)

        async with semaphore:
            try:
                print(
                    f"  [배치 {batch_info}] LLM 요청 시작 "
                    f"(attempt {attempt+1}/{max_retries}, est_tokens≈{est_total_tokens}, RPM={OPENAI_RPM}, TPM={OPENAI_TPM})",
                    flush=True
                )

                timeout = aiohttp.ClientTimeout(total=OPENAI_TIMEOUT_SEC)

                async with session.post(API_ENDPOINT, headers=headers, json=data, timeout=timeout) as res:
                    if res.status == 429:
                        # Retry-After 우선
                        ra = res.headers.get("Retry-After")
                        if ra:
                            try:
                                wait = float(ra)
                            except ValueError:
                                wait = 30.0
                        else:
                            base = min(60.0, 2.0 ** attempt)
                            wait = base + random.uniform(0.0, 1.5)

                        # 응답 바디에 insufficient_quota가 있으면 재시도 의미 없는 경우가 많음
                        try:
                            err_json = await res.json()
                            err_code = (err_json.get("error", {}).get("code") or "")
                            if "insufficient_quota" in str(err_code).lower():
                                print(f"  [배치 {batch_info}] 429(insufficient_quota) - 중단", flush=True)
                                return "API 호출 실패"
                        except Exception:
                            pass

                        print(f"  [배치 {batch_info}] 429 RateLimit - {wait:.1f}s 대기 후 재시도", flush=True)
                        await asyncio.sleep(wait)
                        continue

                    if res.status == 401:
                        # 401 Unauthorized: API 키 문제
                        print(f"  [배치 {batch_info}] 401 Unauthorized - API 키 확인 필요", flush=True)
                        print(f"  [배치 {batch_info}] API 키가 올바른지 확인하세요:", flush=True)
                        print(f"  [배치 {batch_info}] - API 키가 .env 파일에 올바르게 설정되었는지", flush=True)
                        print(f"  [배치 {batch_info}] - API 키가 만료되지 않았는지", flush=True)
                        print(f"  [배치 {batch_info}] - API 키 형식이 올바른지 (sk-로 시작)", flush=True)
                        return "API 호출 실패"

                    if 500 <= res.status < 600:
                        wait = min(60.0, 2.0 ** attempt) + random.uniform(0.0, 1.5)
                        print(f"  [배치 {batch_info}] 서버 오류 {res.status} - {wait:.1f}s 후 재시도", flush=True)
                        await asyncio.sleep(wait)
                        continue

                    res.raise_for_status()
                    data_json = await res.json()
                    content = data_json["choices"][0]["message"]["content"]
                    return content.strip()

            except asyncio.TimeoutError:
                wait = min(60.0, 2.0 ** attempt) + random.uniform(0.0, 1.5)
                print(f"  [배치 {batch_info}] 타임아웃 - {wait:.1f}s 후 재시도", flush=True)
                await asyncio.sleep(wait)

            except aiohttp.ClientResponseError as e:
                if getattr(e, "status", None) == 429:
                    wait = min(60.0, 2.0 ** attempt) + random.uniform(0.0, 1.5)
                    print(f"  [배치 {batch_info}] 429(예외) - {wait:.1f}s 후 재시도", flush=True)
                    await asyncio.sleep(wait)
                    continue
                if getattr(e, "status", None) == 401:
                    print(f"  [배치 {batch_info}] 401 Unauthorized - API 키 확인 필요", flush=True)
                    print(f"  [배치 {batch_info}] API 키가 올바른지 확인하세요.", flush=True)
                    return "API 호출 실패"
                print(f"  [배치 {batch_info}] HTTP 오류: {e}", flush=True)
                return "API 호출 실패"

            except Exception as e:
                wait = min(30.0, 2.0 ** attempt) + random.uniform(0.0, 1.5)
                print(f"  [배치 {batch_info}] 기타 오류: {e} - {wait:.1f}s 후 재시도", flush=True)
                await asyncio.sleep(wait)

    print(f"  [배치 {batch_info}] 최대 재시도 초과 - 실패", flush=True)
    return "API 호출 실패"

def save_results_to_sheets(results_df, spreadsheet_id, worksheet_name):
    """결과를 Google Sheets에 저장 (기존 데이터 유지하고 이어서 추가)"""
    client = get_google_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        existing_data = worksheet.get_all_values()
        has_header = len(existing_data) > 0
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=10)
        has_header = False

    output_cols = ["사업명", "경쟁사", "협력사/기관명", "협력 유형", "근거 기사 제목", "근거 기사 URL", "기사 날짜"]

    if not has_header:
        worksheet.append_row(output_cols)

    for _, row in results_df.iterrows():
        worksheet.append_row([
            row.get("사업명", ""),
            row.get("경쟁사", ""),
            row.get("협력사/기관명", ""),
            row.get("협력 유형", ""),
            row.get("근거 기사 제목", ""),
            row.get("근거 기사 URL", ""),
            row.get("기사 날짜", "")
        ])

    return len(results_df)

def get_column_letter(col_num):
    """컬럼 번호를 A1 표기법의 열 문자로 변환 (1-based)"""
    result = ""
    while col_num > 0:
        col_num -= 1
        result = chr(65 + (col_num % 26)) + result
        col_num //= 26
    return result

def update_input_sheet_status(worksheet, row_numbers, status_value):
    """입력 시트의 특정 행들의 status 컬럼 업데이트
    
    Args:
        worksheet: gspread worksheet 객체
        row_numbers: 시트 행 번호 리스트 (헤더 제외, 2부터 시작하는 실제 행 번호)
        status_value: 업데이트할 status 값 (DONE, ERROR 등)
    """
    try:
        all_values = worksheet.get_all_values()
        if len(all_values) <= 1:
            return
        
        headers = all_values[0]
        status_col_idx = None
        for idx, h in enumerate(headers):
            if h.lower() == 'status':
                status_col_idx = idx
                break
        
        # status 컬럼이 없으면 추가
        if status_col_idx is None:
            # 헤더에 status 추가
            col_letter = get_column_letter(len(headers) + 1)
            worksheet.update(f'{col_letter}1', 'status')
            status_col_idx = len(headers)
        
        # 각 행의 status 업데이트 (배치 업데이트)
        updates = []
        col_letter = get_column_letter(status_col_idx + 1)
        for row_num in row_numbers:
            # row_num은 이미 시트의 실제 행 번호 (2부터 시작, 1-based)
            cell_range = f'{col_letter}{row_num}'
            updates.append({
                'range': cell_range,
                'values': [[status_value]]
            })
        
        if updates:
            # 배치 업데이트 (최대 100개씩)
            batch_size = 100
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                worksheet.batch_update(batch)
            print(f"  입력 시트 status 업데이트: {len(updates)}개 행을 '{status_value}'로 업데이트", flush=True)
        
    except Exception as e:
        print(f"  입력 시트 status 업데이트 오류: {e}", flush=True)
        import traceback
        traceback.print_exc()

def save_batch_results(accumulated_results, batch_save_size, spreadsheet_id, worksheet_name):
    """누적된 결과를 배치 단위로 저장하는 헬퍼 함수"""
    saved_count = 0
    output_cols = ["사업명", "경쟁사", "협력사/기관명", "협력 유형", "근거 기사 제목", "근거 기사 URL", "기사 날짜"]
    
    while len(accumulated_results) >= batch_save_size:
        try:
            batch_to_save = accumulated_results[:batch_save_size]
            batch_df_save = pd.DataFrame(batch_to_save)
            
            # 컬럼이 없으면 빈 문자열로 추가
            for col in output_cols:
                if col not in batch_df_save.columns:
                    batch_df_save[col] = ""
            
            print(f"[배치 저장] {len(batch_df_save)}개 행 저장 시작...", flush=True)
            count = save_results_to_sheets(
                batch_df_save[output_cols], 
                spreadsheet_id, 
                worksheet_name
            )
            saved_count += count
            print(f"[배치 저장 완료] {count}개 행 저장됨 (누적: {saved_count}개)", flush=True)
            
            # 저장한 부분 제거
            accumulated_results = accumulated_results[batch_save_size:]
            
        except Exception as e:
            print(f"[배치 저장 오류] {e}", flush=True)
            import traceback
            traceback.print_exc()
            break
    
    return saved_count, accumulated_results

async def process_batch_async(session, semaphore, batch_df, competitor, batch_index, business_name, url_col):
    """배치 하나 처리
    
    Returns:
        tuple: (결과 리스트, 처리된 행 번호 리스트, 상태 문자열)
               상태: 'DONE' (성공), 'ERROR' (API 실패), 'SKIP' (빈 CSV)
    """
    analysis_data = []
    processed_row_nums = []  # 처리된 시트 행 번호 추적
    
    for idx, row in batch_df.iterrows():
        # 시트 행 번호 추적 (_sheet_row_num 컬럼에서 가져오기)
        if '_sheet_row_num' in batch_df.columns:
            processed_row_nums.append(row['_sheet_row_num'])
        # 본문 길이 제한 (토큰 절약 및 API 비용 절감)
        content = str(row['본문'])
        if len(content) > MAX_ARTICLE_CONTENT_LENGTH:
            content = content[:MAX_ARTICLE_CONTENT_LENGTH] + "..."
        
        item = {
            "기사 제목": row['제목'],
            "기사 본문": content,
        }
        if url_col:
            item["기사 URL"] = row[url_col]
        analysis_data.append(item)

    data_json = json.dumps(analysis_data, ensure_ascii=False, indent=2)
    prompt = make_prompt(competitor, data_json, business_name)

    batch_info = f"{competitor}-{batch_index}"
    csv_text = await call_llm_async(session, semaphore, prompt, batch_info)

    if csv_text in ("API 호출 실패", "응답 처리 실패"):
        print(f"  [배치 실패] 배치 {batch_index} - LLM 호출 실패", flush=True)
        # API 실패: ERROR 상태로 반환
        return [], processed_row_nums, 'ERROR'

    try:
        csv_text_stripped = csv_text.strip()
        if not csv_text_stripped:
            print(f"  [배치 경고] 배치 {batch_index} - 빈 CSV (SKIP 처리)", flush=True)
            # 빈 CSV: SKIP 상태로 반환
            return [], processed_row_nums, 'SKIP'

        if csv_text_stripped.startswith("```"):
            csv_text_stripped = re.sub(r"^```[a-zA-Z]*", "", csv_text_stripped)
            csv_text_stripped = csv_text_stripped.rstrip("`").strip()

        f = StringIO(csv_text_stripped)
        reader = csv.DictReader(f)

        batch_rows = []
        for row in reader:
            # CSV에서 협력사/기관명 추출 (경쟁사 이름과 동일하면 제외)
            partner_name = str(row.get("협력사/기관명", "")).strip()
            
            # 협력사/기관명이 경쟁사 이름과 동일하거나 비어있으면 스킵
            if partner_name == competitor or not partner_name:
                continue
            
            llm_title = str(row.get("근거 기사 제목", "")).strip()

            matched_title = ""
            matched_url = ""
            original_title_for_date = ""  # 날짜 추출용 원본 제목

            # 원본 제목에서 매칭 찾기
            for _, orig_row in batch_df.iterrows():
                orig_title = str(orig_row.get('제목', '')).strip()
                if orig_title and llm_title:
                    if llm_title in orig_title or orig_title in llm_title:
                        original_title_for_date = orig_title  # 원본 제목 저장 (날짜 포함)
                        if url_col:
                            matched_url = str(orig_row.get(url_col, '')).strip()
                        break
                    elif len(llm_title) > 10 and len(orig_title) > 10:
                        if llm_title[:30] in orig_title or orig_title[:30] in llm_title:
                            original_title_for_date = orig_title  # 원본 제목 저장 (날짜 포함)
                            if url_col:
                                matched_url = str(orig_row.get(url_col, '')).strip()
                            break

            # 매칭된 원본 제목이 없으면 LLM 제목 사용 (하지만 날짜는 없을 수 있음)
            if not original_title_for_date:
                original_title_for_date = llm_title

            # 원본 제목에서 날짜 추출 (원본 제목에 날짜가 포함되어 있음)
            if original_title_for_date:
                date_str, clean_title = extract_date_from_title(original_title_for_date)
                # matched_title 설정: 날짜가 제거된 제목 사용
                if clean_title:
                    matched_title = clean_title
                else:
                    matched_title = original_title_for_date
            else:
                # 원본 제목을 찾지 못한 경우 LLM 제목에서 날짜 추출 시도
                date_str, clean_title = extract_date_from_title(llm_title)
                matched_title = clean_title if clean_title else llm_title

            # 배치 내 원본 행에서 경쟁사 정보 가져오기
            original_competitor = competitor  # 기본값은 배치의 경쟁사
            
            for _, orig_row in batch_df.iterrows():
                orig_title = str(orig_row.get('제목', '')).strip()
                if matched_title and orig_title and (matched_title in orig_title or orig_title in matched_title):
                    original_competitor = str(orig_row.get('경쟁사', competitor)).strip()
                    break
            
            # 사업명 처리: business_name이 있으면 무조건 사용 (특히 콤마로 구분된 여러 사업명의 경우)
            llm_business_name = str(row.get("사업명", "")).strip()
            
            # business_name이 정의되어 있으면 무조건 사용 (LLM 반환값 무시)
            if business_name:
                final_business_name = business_name
            else:
                final_business_name = llm_business_name
            
            batch_rows.append({
                "사업명": final_business_name,
                "경쟁사": original_competitor,  # 원본 데이터의 경쟁사 사용
                "협력사/기관명": partner_name,  # 이미 검증된 값 사용
                "협력 유형": str(row.get("협력 유형", "")).strip(),
                "근거 기사 제목": matched_title,
                "근거 기사 URL": matched_url,
                "기사 날짜": date_str or "",
            })

        print(f"  [배치 완료] 배치 {batch_index} - {len(batch_rows)}개 수집", flush=True)
        return batch_rows, processed_row_nums, 'DONE'

    except Exception as e:
        print(f"  [배치 CSV 파싱 오류] 배치 {batch_index}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return [], processed_row_nums, 'ERROR'

async def main_async():
    print("--- 1. 뉴스 데이터 로드 시작 ---", flush=True)
    df_news, input_worksheet = get_gsheet_data(GS_SPREADSHEET_ID, GS_INPUT_WORKSHEET)

    if df_news is None or len(df_news) == 0:
        print("분석할 데이터가 없습니다.", flush=True)
        return

    print(f"처리할 새로운 기사: {len(df_news)}개 (status가 DONE이 아닌 기사만)", flush=True)

    url_col = None
    for c in df_news.columns:
        lower = c.lower()
        if lower in ("url", "링크", "기사url", "기사 url"):
            url_col = c
            break

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    # 커넥터 제한/캐시로 네트워크 안정성 향상
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_REQUESTS, ttl_dns_cache=300)

    async with aiohttp.ClientSession(connector=connector) as session:
        accumulated_results = []
        total_saved_count = 0
        BATCH_SAVE_SIZE = 5  # 5개씩 모이면 저장

        # 시트 순서대로 배치 처리 (경쟁사별 그룹화 없음)
        total_articles = len(df_news)
        total_batches = (total_articles + ARTICLES_PER_CALL - 1) // ARTICLES_PER_CALL
        pending = set()
        batch_index = 0

        for start in range(0, total_articles, ARTICLES_PER_CALL):
            end = min(start + ARTICLES_PER_CALL, total_articles)
            batch_df = df_news.iloc[start:end].copy()
            batch_index += 1

            # 배치 내 첫 번째 행의 경쟁사 정보 사용 (배치 내 경쟁사가 다를 수 있지만 프롬프트용)
            batch_competitor = str(batch_df.iloc[0].get('경쟁사', '')).strip() if len(batch_df) > 0 else ""
            business_name = COMPETITOR_BUSINESS_MAP.get(batch_competitor, "")

            print(f"  - 배치 {batch_index}/{total_batches}: 기사 {start+1} ~ {end} (경쟁사: {batch_competitor})", flush=True)
            
            task = asyncio.create_task(
                process_batch_async(session, semaphore, batch_df, batch_competitor, batch_index, business_name, url_col)
            )
            pending.add(task)

            if len(pending) >= MAX_BATCH_TASKS_IN_FLIGHT:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for d in done:
                    try:
                        res, row_nums, status = d.result()
                        if row_nums and input_worksheet:
                            if status == 'DONE' and res and len(res) > 0:
                                # 성공적으로 처리된 경우: 'DONE'으로 업데이트
                                accumulated_results.extend(res)
                                update_input_sheet_status(input_worksheet, row_nums, 'DONE')
                                
                                # 5개 이상 모이면 배치 저장
                                count, accumulated_results = save_batch_results(
                                    accumulated_results, BATCH_SAVE_SIZE, 
                                    GS_SPREADSHEET_ID, GS_OUTPUT_WORKSHEET
                                )
                                total_saved_count += count
                            else:
                                # 실패(SKIP 또는 ERROR)인 경우: status 값으로 업데이트
                                update_input_sheet_status(input_worksheet, row_nums, status)
                    except Exception as e:
                        print(f"  [배치 태스크 오류] {e}", flush=True)

        # 남은 태스크 수거
        if pending:
            done, _ = await asyncio.wait(pending)
            for d in done:
                try:
                    res, row_nums, status = d.result()
                    if row_nums and input_worksheet:
                        if status == 'DONE' and res and len(res) > 0:
                            # 성공적으로 처리된 경우: 'DONE'으로 업데이트
                            accumulated_results.extend(res)
                            update_input_sheet_status(input_worksheet, row_nums, 'DONE')
                            
                            # ✅ 5개 이상 모이면 배치 저장
                            count, accumulated_results = save_batch_results(
                                accumulated_results, BATCH_SAVE_SIZE, 
                                GS_SPREADSHEET_ID, GS_OUTPUT_WORKSHEET
                            )
                            total_saved_count += count
                        else:
                            # ✅ 실패(SKIP 또는 ERROR)인 경우: status 값으로 업데이트
                            update_input_sheet_status(input_worksheet, row_nums, status)
                except Exception as e:
                    print(f"  [배치 태스크 오류] {e}", flush=True)
                    # 예외 발생 시 ERROR로 표시
                    try:
                        task_info = getattr(d, '_coro', None)
                        # row_nums는 추적 불가능하므로 스킵
                    except:
                        pass

        # 남은 결과가 있으면 마지막으로 저장
        if accumulated_results:
            try:
                final_df = pd.DataFrame(accumulated_results)
                
                output_cols = ["사업명", "경쟁사", "협력사/기관명", "협력 유형", "근거 기사 제목", "근거 기사 URL", "기사 날짜"]
                for col in output_cols:
                    if col not in final_df.columns:
                        final_df[col] = ""
                
                print(f"[최종 저장] 남은 {len(final_df)}개 행 저장 시작...", flush=True)
                saved_count = save_results_to_sheets(
                    final_df[output_cols], 
                    GS_SPREADSHEET_ID, 
                    GS_OUTPUT_WORKSHEET
                )
                total_saved_count += saved_count
                print(f"[최종 저장 완료] {saved_count}개 행 저장됨", flush=True)
                
            except Exception as e:
                print(f"[최종 저장 오류] {e}", flush=True)
                import traceback
                traceback.print_exc()

    if total_saved_count == 0:
        print("\n저장된 파트너십 데이터가 없습니다.", flush=True)
    else:
        print(f"\n{'='*50}", flush=True)
        print(f"전체 분석 완료: 총 {total_saved_count}개 행이 Google Sheets '{GS_OUTPUT_WORKSHEET}'에 저장되었습니다.", flush=True)
        print(f"{'='*50}\n", flush=True)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()