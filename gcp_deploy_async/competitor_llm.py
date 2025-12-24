#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
경쟁사 뉴스 기반 LLM 분석 스크립트 (비동기 처리 버전)

1) Google Sheets에서 경쟁사 뉴스 데이터 로드
2) 경쟁사별 기사들을 배치로 나눠 LLM 분석 → 파트너십 목록 생성
3) 결과를 Google Sheets에 저장 (기사 제목에서 날짜 추출 포함)

"""

import pandas as pd
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import sys
import os
import time
import csv
from io import StringIO
from dotenv import load_dotenv
import re
import asyncio
import aiohttp

#  추가 import (레이트리밋/백오프)
import random
from collections import deque

# .env 파일 로드 (현재 디렉토리 및 부모 디렉토리에서 찾기)
from pathlib import Path
env_paths = [
    Path(__file__).parent / '.env',
    Path(__file__).parent.parent / '.env',
]
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()  # 기본 경로에서도 시도

API_KEY = os.getenv('OPENAI_API_KEY')
API_ENDPOINT = os.getenv('OPENAI_API_ENDPOINT', 'https://api.openai.com/v1/chat/completions')

# credentials.json 경로 찾기 (현재 파일 기준 상대 경로)
_script_dir = Path(__file__).parent
_cred_file_default = _script_dir / 'credentials.json'
if not _cred_file_default.exists():
    _cred_file_default = _script_dir.parent / 'credentials.json'
GS_CRED_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', str(_cred_file_default))
GS_SPREADSHEET_ID = os.getenv('GOOGLE_SPREADSHEET_ID', '1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8')
GS_INPUT_WORKSHEET = os.getenv('GOOGLE_INPUT_WORKSHEET', '경쟁사 동향 분석')
GS_OUTPUT_WORKSHEET = os.getenv('GOOGLE_OUTPUT_WORKSHEET', '경쟁사 협업 기업 리스트')

# LLM 분석 설정
ARTICLES_PER_CALL = int(os.getenv("ARTICLES_PER_CALL", "10"))  # 배치당 기사 수 (기본값: 10, API 사용량 감소를 위해 5→10으로 증가)
MAX_ARTICLE_CONTENT_LENGTH = int(os.getenv("MAX_ARTICLE_CONTENT_LENGTH", "2000"))  # 기사 본문 최대 길이 (글자 수, API 사용량 감소)

# 비동기 처리 설정
MAX_CONCURRENT_REQUESTS = 2  # 동시 요청 수 (세마포어)
MAX_BATCH_TASKS_IN_FLIGHT = int(os.getenv("MAX_BATCH_TASKS_IN_FLIGHT", str(MAX_CONCURRENT_REQUESTS * 2)))
# ↑ 배치 태스크를 한 경쟁사에서 동시에 “실행 상태”로 유지할 개수(메모리/버스트 방지)

if not API_KEY:
    raise ValueError("OPENAI_API_KEY가 .env 파일에 설정되지 않았습니다. .env.example을 참고하세요.")

# ---------------------------
#  Rate Limit(핵심 수정)
# ---------------------------
# 계정/모델 제한이 다르므로 env로 쉽게 조절
OPENAI_RPM = int(os.getenv("OPENAI_RPM", "10"))          # 요청/분(보수적으로)
OPENAI_TPM = int(os.getenv("OPENAI_TPM", "20000"))       # 토큰/분(보수적으로)
OPENAI_TIMEOUT_SEC = int(os.getenv("OPENAI_TIMEOUT_SEC", "180"))  # LLM 응답 대기(초)

def estimate_tokens(text: str) -> int:
    """
    토큰 수 러프 추정.
    실제 토크나이저를 쓰면 정확하지만, 여기선 안전하게 'chars/3'로 넉넉히 잡음.
    → TPM 초과를 줄이는 목적.
    """
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
    
    # credentials 파일 존재 확인
    if not os.path.exists(GS_CRED_FILE):
        raise FileNotFoundError(
            f"Google credentials 파일을 찾을 수 없습니다: {GS_CRED_FILE}\n"
            f"현재 작업 디렉토리: {os.getcwd()}\n"
            f"파일 절대 경로: {os.path.abspath(GS_CRED_FILE)}"
        )
    
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(GS_CRED_FILE, scope)
        return gspread.authorize(creds)
    except Exception as e:
        raise Exception(f"Google 클라이언트 인증 실패 (파일: {GS_CRED_FILE}): {e}")

def get_gsheet_data(spreadsheet_id, worksheet_name):
    """Google Sheets 데이터를 Pandas DataFrame으로 로드"""
    try:
        client = get_google_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        df = pd.DataFrame(worksheet.get_all_records())

        url_col = None
        for c in df.columns:
            lower = c.lower()
            if lower in ("url", "링크", "기사url", "기사 url"):
                url_col = c
                break

        required_cols = ['경쟁사', '제목', '본문']
        if not all(col in df.columns for col in required_cols):
            print("오류: 데이터에 '경쟁사', '제목', '본문' 컬럼이 부족합니다.", flush=True)
            return None

        cols = required_cols.copy()
        if url_col:
            cols.append(url_col)

        df = df[cols]
        df = df[df['본문'].astype(str).str.len() > 100].reset_index(drop=True)
        return df

    except Exception as e:
        print(f"Google Sheets 로드 실패: {e}", flush=True)
        return None

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

def add_article_dates(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame에 '기사 날짜' 컬럼 추가 (제목에서 추출)"""
    if "근거 기사 제목" not in df.columns:
        return df

    titles, dates = [], []
    for _, row in df.iterrows():
        title = row.get("근거 기사 제목", "")
        date_str, clean_title = extract_date_from_title(title)
        titles.append(clean_title)
        dates.append(date_str or "")

    df = df.copy()
    df["근거 기사 제목"] = titles
    df["기사 날짜"] = dates
    return df

def make_prompt(competitor, data_json, business_name=None):
    """경쟁사별 협력사 추출을 위한 프롬프트 생성"""
    if business_name:
        business_text = f"대웅그룹의 **'{business_name}'** 사업과 직접적으로 연관된 경쟁사입니다."
        business_hint = f"CSV의 '사업명' 컬럼에는 모든 행에서 **'{business_name}'**을 그대로 사용하세요."
    else:
        business_text = "대웅그룹과 연관된 경쟁사입니다."
        business_hint = "사업명이 명확하지 않은 경우, '사업명' 컬럼은 비워 두거나 기사 맥락상 자연스러운 이름을 사용하세요."

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

[분석용 기사 데이터(JSON)]
{data_json}

출력 형식 요구 사항 (매우 중요):

1. 출력은 **순수 CSV 텍스트만** 포함해야 합니다.
   - 코드 블록, 설명 문장, 주석, 인용구, 마크다운 표 등은 절대 포함하지 마세요.
   - 오직 CSV 행들만 출력하세요.

2. 첫 번째 줄은 반드시 **헤더**로 아래 순서를 그대로 사용합니다.
   - 번호,사업명,경쟁사,협력사/기관명,협력 유형,근거 기사 제목,근거 기사 URL

3. 각 데이터 행은 아래 의미를 가집니다.
   - 번호: 일련번호 (1부터 시작). 비워 두어도 됩니다.
   - 사업명: {business_hint}
   - 경쟁사: '{competitor}'를 그대로 입력하세요.
   - 협력사/기관명: '{competitor}'와 직접적인 파트너십/협력 관계에 있는 회사 또는 기관명
   - 협력 유형: 기사에 근거한 구체적인 협력 형태(예: EAP 도입, 공동 연구, 기술 연동, 투자 유치, 서비스 도입 등)
   - 근거 기사 제목: 해당 파트너십이 언급된 기사 제목 (JSON의 "기사 제목"에서 그대로 가져오기)
   - 근거 기사 URL: JSON에 "기사 URL"이 있을 경우 그 값을 그대로 사용, 없으면 빈 칸으로 남김

4. CSV 형식 세부 규칙:
   - 구분자는 쉼표(,)를 사용합니다.
   - 필드 안에 쉼표나 줄바꿈이 들어가는 경우에는 그 필드를 큰따옴표(")로 감싸세요.
   - 헤더를 제외한 데이터 행이 하나도 없을 수도 있습니다. 그 경우 헤더만 출력하세요.

위 조건을 모두 지키면서 CSV를 출력하세요.
"""
    return prompt

# ---------------------------
# LLM 호출 (핵심 수정)
# ---------------------------
async def call_llm_async(session, semaphore, prompt, batch_info, max_retries=6):
    """
    - RPM/TPM 제한 적용
    - 429: Retry-After 우선, 없으면 지수 백오프 + 지터
    - 5xx: 백오프 후 재시도
    """
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    # 모델 선택: gpt-4o (기본값), gpt-4o-mini (비용 절감), gpt-3.5-turbo (최대 절감)
    # gpt-4o-mini: 비용 94% 절감, 성능 약간 저하 가능
    # gpt-3.5-turbo: 비용 96% 절감, CSV 형식 준수 실패 가능성 높음 (비권장)
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # 기본값을 gpt-4o-mini로 변경 (비용 절감)
    
    data = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.0
    }

    est_prompt_tokens = estimate_tokens(prompt)
    est_total_tokens = est_prompt_tokens + int(data["max_tokens"])

    for attempt in range(max_retries):
        #  RPM/TPM 제한: 여기서 “스스로 기다리면서” 429를 근본적으로 줄임
        await rpm_limiter.acquire(1)
        await tpm_limiter.acquire(est_total_tokens)

        async with semaphore:
            try:
                if attempt == 0:
                    print(
                        f"  [배치 {batch_info}] LLM 요청 시작 "
                        f"(est_tokens≈{est_total_tokens}, RPM={OPENAI_RPM}, TPM={OPENAI_TPM})",
                        flush=True
                    )
                else:
                    print(
                        f"  [배치 {batch_info}] 재시도 {attempt+1}/{max_retries}",
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

                        # 응답 바디에 insufficient_quota가 있으면 재시도 의미 없음 (할당량 소진)
                        try:
                            err_json = await res.json()
                            err_info = err_json.get("error", {})
                            err_code = (err_info.get("code") or "").lower()
                            err_message = err_info.get("message", "")
                            
                            if "insufficient_quota" in err_code or "quota" in err_message.lower():
                                print(f"  [배치 {batch_info}] ❌ OpenAI API 할당량 소진 (insufficient_quota)", flush=True)
                                print(f"  [배치 {batch_info}] 💡 해결 방법:", flush=True)
                                print(f"  [배치 {batch_info}]    1. OpenAI 계정 사용량 확인: https://platform.openai.com/usage", flush=True)
                                print(f"  [배치 {batch_info}]    2. 결제 정보 확인 및 크레딧 충전", flush=True)
                                print(f"  [배치 {batch_info}]    3. API 키 확인 (올바른 키인지)", flush=True)
                                return "API 호출 실패 (할당량 소진)"
                        except Exception:
                            pass

                        print(f"  [배치 {batch_info}] 429 RateLimit → {wait:.1f}s 대기 후 재시도", flush=True)
                        await asyncio.sleep(wait)
                        continue

                    if 500 <= res.status < 600:
                        wait = min(60.0, 2.0 ** attempt) + random.uniform(0.0, 1.5)
                        print(f"  [배치 {batch_info}] 서버 오류 {res.status} → {wait:.1f}s 후 재시도", flush=True)
                        await asyncio.sleep(wait)
                        continue

                    res.raise_for_status()
                    data_json = await res.json()
                    content = data_json["choices"][0]["message"]["content"]
                    return content.strip()

            except asyncio.TimeoutError:
                wait = min(60.0, 2.0 ** attempt) + random.uniform(0.0, 1.5)
                print(f"  [배치 {batch_info}] 타임아웃 → {wait:.1f}s 후 재시도", flush=True)
                await asyncio.sleep(wait)

            except aiohttp.ClientResponseError as e:
                if getattr(e, "status", None) == 429:
                    wait = min(60.0, 2.0 ** attempt) + random.uniform(0.0, 1.5)
                    print(f"  [배치 {batch_info}] 429(예외) → {wait:.1f}s 후 재시도", flush=True)
                    await asyncio.sleep(wait)
                    continue
                print(f"  [배치 {batch_info}] HTTP 오류: {e}", flush=True)
                return "API 호출 실패"

            except Exception as e:
                wait = min(30.0, 2.0 ** attempt) + random.uniform(0.0, 1.5)
                print(f"  [배치 {batch_info}] 기타 오류: {e} → {wait:.1f}s 후 재시도", flush=True)
                await asyncio.sleep(wait)

    print(f"  [배치 {batch_info}] 최대 재시도 초과 → 실패", flush=True)
    return "API 호출 실패"

def save_results_to_sheets(results_df, spreadsheet_id, worksheet_name):
    """결과를 Google Sheets에 저장 (기존 데이터 유지하고 이어서 추가)"""
    try:
        print(f"[저장] 시작: 시트='{worksheet_name}', 행 수={len(results_df)}, 스프레드시트 ID={spreadsheet_id}", flush=True)
        
        client = get_google_client()
        print(f"[저장] Google 클라이언트 연결 성공", flush=True)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        print(f"[저장] 스프레드시트 열기 성공: {spreadsheet.title}", flush=True)
        
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
            existing_data = worksheet.get_all_values()
            has_header = len(existing_data) > 0
            print(f"[저장] 기존 시트 사용 (기존 행: {len(existing_data)})", flush=True)
        except Exception as e:
            print(f"[저장] 새 시트 생성 시도: {e}", flush=True)
            worksheet = spreadsheet.add_worksheet(
                title=worksheet_name, rows=1000, cols=10
            )
            has_header = False
            print(f"[저장] 새 시트 생성 완료", flush=True)
        
        output_cols = ["사업명", "경쟁사", "협력사/기관명", "협력 유형", "근거 기사 제목", "근거 기사 URL", "기사 날짜"]
        
        # 헤더가 없으면 추가
        if not has_header:
            worksheet.append_row(output_cols)
            print(f"[저장] 헤더 추가 완료", flush=True)
        
        # 데이터 추가 (기존 데이터 아래에 이어서)
        saved_count = 0
        for idx, (_, row) in enumerate(results_df.iterrows(), 1):
            try:
                row_data = [
                    str(row.get("사업명", "")),
                    str(row.get("경쟁사", "")),
                    str(row.get("협력사/기관명", "")),
                    str(row.get("협력 유형", "")),
                    str(row.get("근거 기사 제목", "")),
                    str(row.get("근거 기사 URL", "")),
                    str(row.get("기사 날짜", ""))
                ]
                worksheet.append_row(row_data)
                saved_count += 1
                if idx % 10 == 0:
                    print(f"[저장] 진행: {idx}/{len(results_df)} 행 저장됨", flush=True)
            except Exception as row_error:
                print(f"[저장] 행 {idx} 저장 실패: {row_error}", flush=True)
                continue
        
        print(f"[저장] 완료: {saved_count}/{len(results_df)}개 행 저장됨", flush=True)
        return saved_count
        
    except Exception as e:
        print(f"[저장] 치명적 오류: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise

def get_already_processed_urls(spreadsheet_id, worksheet_name):
    """이미 처리된 기사 URL 목록 가져오기"""
    try:
        client = get_google_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        existing_data = worksheet.get_all_values()

        if len(existing_data) <= 1:
            return set()

        headers = existing_data[0]
        processed_urls = set()

        url_col_idx = None
        for idx, h in enumerate(headers):
            if h.lower() in ("근거 기사 url", "근거기사url", "url", "링크"):
                url_col_idx = idx
                break

        if url_col_idx is not None:
            for row in existing_data[1:]:
                if len(row) > url_col_idx and row[url_col_idx]:
                    processed_urls.add(row[url_col_idx].strip())

        return processed_urls
    except Exception:
        return set()

async def process_batch_async(session, semaphore, batch_df, competitor, batch_index, business_name, url_col):
    """배치 하나 처리"""
    analysis_data = []
    for _, row in batch_df.iterrows():
        # 기사 본문 길이 제한 (API 사용량 감소)
        content = str(row['본문'])[:MAX_ARTICLE_CONTENT_LENGTH]
        if len(str(row['본문'])) > MAX_ARTICLE_CONTENT_LENGTH:
            content += "... (본문 일부만 표시됨)"
        
        item = {
            "기사 제목": row['제목'],
            "기사 본문": content,  # 길이 제한된 본문만 전송
        }
        if url_col:
            item["기사 URL"] = row[url_col]
        analysis_data.append(item)

    data_json = json.dumps(analysis_data, ensure_ascii=False, indent=2)
    prompt = make_prompt(competitor, data_json, business_name)

    batch_info = f"{competitor}-{batch_index}"
    csv_text = await call_llm_async(session, semaphore, prompt, batch_info)

    if csv_text in ("API 호출 실패", "응답 처리 실패"):
        print(f"  [배치 실패] {competitor} 배치 {batch_index} - LLM 호출 실패", flush=True)
        return []

    try:
        csv_text_stripped = csv_text.strip()
        if not csv_text_stripped:
            print(f"  [배치 경고] {competitor} 배치 {batch_index} - 빈 CSV", flush=True)
            return []

        if csv_text_stripped.startswith("```"):
            csv_text_stripped = re.sub(r"^```[a-zA-Z]*", "", csv_text_stripped)
            csv_text_stripped = csv_text_stripped.rstrip("`").strip()

        f = StringIO(csv_text_stripped)
        reader = csv.DictReader(f)

        batch_rows = []
        for row in reader:
            llm_title = str(row.get("근거 기사 제목", "")).strip()

            matched_title = ""
            matched_url = ""
            date_str = None  # 날짜는 원본 제목에서 추출

            for _, orig_row in batch_df.iterrows():
                orig_title = str(orig_row.get('제목', '')).strip()
                if orig_title and llm_title:
                    if llm_title in orig_title or orig_title in llm_title:
                        matched_title = orig_title
                        if url_col:
                            matched_url = str(orig_row.get(url_col, '')).strip()
                        # 원본 제목에서 날짜 추출
                        date_str, clean_title = extract_date_from_title(orig_title)
                        matched_title = clean_title  # 날짜 제거된 제목 사용
                        break
                    elif len(llm_title) > 10 and len(orig_title) > 10:
                        if llm_title[:30] in orig_title or orig_title[:30] in llm_title:
                            matched_title = orig_title
                            if url_col:
                                matched_url = str(orig_row.get(url_col, '')).strip()
                            # 원본 제목에서 날짜 추출
                            date_str, clean_title = extract_date_from_title(orig_title)
                            matched_title = clean_title  # 날짜 제거된 제목 사용
                            break

            # 매칭 실패 시 LLM 제목 사용 및 날짜 추출
            if not matched_title:
                matched_title = llm_title
                date_str, matched_title = extract_date_from_title(matched_title)

            batch_rows.append({
                "사업명": business_name or row.get("사업명", ""),
                "경쟁사": competitor,
                "협력사/기관명": row.get("협력사/기관명", ""),
                "협력 유형": row.get("협력 유형", ""),
                "근거 기사 제목": matched_title,
                "근거 기사 URL": matched_url,
                "기사 날짜": date_str or "",
            })

        print(f"  [배치 완료] {competitor} 배치 {batch_index} - {len(batch_rows)}개 수집", flush=True)
        return batch_rows

    except Exception as e:
        print(f"  [배치 CSV 파싱 오류] {competitor} 배치 {batch_index}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return []

async def process_competitor_async(session, semaphore, competitor, full_group_df, business_name, url_col):
    """경쟁사 하나의 모든 배치를 처리"""
    total_articles = len(full_group_df)
    print(f"\n[분석 시작] 경쟁사: {competitor} (총 {total_articles}개 기사)", flush=True)

    total_batches = (total_articles + ARTICLES_PER_CALL - 1) // ARTICLES_PER_CALL
    all_rows = []

    # (수정) 태스크를 한꺼번에 gather로 폭발시키지 않고
    # in-flight 개수를 제한하며 순차적으로 “발사”
    pending = set()
    batch_index = 0

    for start in range(0, total_articles, ARTICLES_PER_CALL):
        end = min(start + ARTICLES_PER_CALL, total_articles)
        batch_df = full_group_df.iloc[start:end].copy()
        batch_index += 1

        print(f"  - 배치 {batch_index}/{total_batches}: 기사 {start+1} ~ {end} 준비", flush=True)
        task = asyncio.create_task(
            process_batch_async(session, semaphore, batch_df, competitor, batch_index, business_name, url_col)
        )
        pending.add(task)

        if len(pending) >= MAX_BATCH_TASKS_IN_FLIGHT:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                try:
                    res = d.result()
                    all_rows.extend(res)
                except Exception as e:
                    print(f"  [배치 태스크 오류] {e}", flush=True)

    # 남은 태스크 수거
    if pending:
        done, _ = await asyncio.wait(pending)
        for d in done:
            try:
                res = d.result()
                all_rows.extend(res)
            except Exception as e:
                print(f"  [배치 태스크 오류] {e}", flush=True)

    # Rate limiter가 있으므로 긴 대기 시간 불필요 (최소한만 대기)
    # 필요시 .env에서 BATCH_SLEEP_SECONDS 설정 가능
    batch_sleep = int(os.getenv("BATCH_SLEEP_SECONDS", "5"))
    if batch_sleep > 0:
        await asyncio.sleep(batch_sleep)
    return all_rows

async def main_async():
    print("=" * 60, flush=True)
    print(f"LLM 분석 시작", flush=True)
    print(f"입력 시트: '{GS_INPUT_WORKSHEET}'", flush=True)
    print(f"출력 시트: '{GS_OUTPUT_WORKSHEET}'", flush=True)
    print(f"스프레드시트 ID: {GS_SPREADSHEET_ID}", flush=True)
    print("=" * 60, flush=True)
    print("--- 1. 뉴스 데이터 로드 시작 ---", flush=True)
    df_news = get_gsheet_data(GS_SPREADSHEET_ID, GS_INPUT_WORKSHEET)

    if df_news is None or len(df_news) == 0:
        print("분석할 데이터가 없습니다.", flush=True)
        return

    url_col = None
    for c in df_news.columns:
        lower = c.lower()
        if lower in ("url", "링크", "기사url", "기사 url"):
            url_col = c
            break

    print("--- 1-1. 이미 처리된 기사 확인 중 ---", flush=True)
    processed_urls = get_already_processed_urls(GS_SPREADSHEET_ID, GS_OUTPUT_WORKSHEET)
    print(f"이미 처리된 기사: {len(processed_urls)}개", flush=True)

    if url_col:
        df_news = df_news[~df_news[url_col].isin(processed_urls)].reset_index(drop=True)

    if len(df_news) == 0:
        print("처리할 새로운 기사가 없습니다.", flush=True)
        return

    print(f"처리할 새로운 기사: {len(df_news)}개", flush=True)

    competitor_groups = df_news.groupby('경쟁사')
    print(f"총 {len(competitor_groups)}개 경쟁사 데이터 로드 완료.", flush=True)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    #  (권장) 커넥터 제한/캐시로 네트워크 안정성 향상
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_REQUESTS, ttl_dns_cache=300)

    async with aiohttp.ClientSession(connector=connector) as session:
        total_saved_count = 0
        
        # 헤더가 이미 있는지 확인 (첫 번째 경쟁사에서만 헤더 체크)
        header_initialized = False
        
        # 경쟁사별 순차 처리 및 즉시 저장 (점진적 저장)
        for competitor, full_group_df in competitor_groups:
            business_name = COMPETITOR_BUSINESS_MAP.get(competitor, "")

            competitor_results = await process_competitor_async(
                session, semaphore, competitor, full_group_df, business_name, url_col
            )
            
            # ✅ 경쟁사별로 결과가 있으면 즉시 시트에 저장
            print(f"\n{'='*60}", flush=True)
            print(f"[경쟁사 처리 완료] {competitor}: 결과 개수={len(competitor_results) if competitor_results else 0}", flush=True)
            print(f"[경쟁사 처리 완료] {competitor}: 결과 타입={type(competitor_results)}", flush=True)
            if competitor_results:
                print(f"[경쟁사 처리 완료] {competitor}: 결과 샘플 (첫 1개): {competitor_results[0] if len(competitor_results) > 0 else '없음'}", flush=True)
            print(f"{'='*60}", flush=True)
            
            if competitor_results and len(competitor_results) > 0:
                try:
                    competitor_df = pd.DataFrame(competitor_results)
                    print(f"[경쟁사 저장] {competitor}: DataFrame 생성 완료", flush=True)
                    print(f"  - 행 수: {len(competitor_df)}", flush=True)
                    print(f"  - 컬럼: {list(competitor_df.columns)}", flush=True)
                    
                    output_cols = ["사업명", "경쟁사", "협력사/기관명", "협력 유형", "근거 기사 제목", "근거 기사 URL", "기사 날짜"]
                    for col in output_cols:
                        if col not in competitor_df.columns:
                            competitor_df[col] = ""
                            print(f"[경쟁사 저장] {competitor}: 컬럼 '{col}' 추가 (빈 값)", flush=True)
                    
                    print(f"\n[경쟁사 저장] {competitor}: 시트에 저장 시작", flush=True)
                    print(f"  - 저장할 행 수: {len(competitor_df)}", flush=True)
                    print(f"  - 스프레드시트 ID: {GS_SPREADSHEET_ID}", flush=True)
                    print(f"  - 시트 이름: '{GS_OUTPUT_WORKSHEET}'", flush=True)
                    
                    saved_count = save_results_to_sheets(
                        competitor_df[output_cols], 
                        GS_SPREADSHEET_ID, 
                        GS_OUTPUT_WORKSHEET
                    )
                    
                    total_saved_count += saved_count
                    print(f"\n[경쟁사 저장 완료] {competitor}: {saved_count}개 행 저장됨 (누적: {total_saved_count}개)", flush=True)
                    print(f"{'='*60}\n", flush=True)
                    
                except Exception as e:
                    print(f"\n[경쟁사 저장 오류] {competitor}: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    print(f"{'='*60}\n", flush=True)
            else:
                print(f"[경쟁사 저장] {competitor}: 결과가 없어 저장하지 않음\n", flush=True)

            # Rate limiter가 있으므로 긴 대기 시간 불필요 (최소한만 대기)
            competitor_sleep = int(os.getenv("COMPETITOR_SLEEP_SECONDS", "5"))
            if competitor_sleep > 0:
                print(f"[경쟁사 완료] {competitor} 완료. {competitor_sleep}초 대기", flush=True)
                await asyncio.sleep(competitor_sleep)
            else:
                print(f"[경쟁사 완료] {competitor} 완료", flush=True)

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