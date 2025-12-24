#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
경쟁사 뉴스 기반 LLM 분석 스크립트

1) Google Sheets에서 경쟁사 뉴스 데이터 로드
2) 경쟁사별로 기사들을 여러 번(배치) 나눠서 LLM에 전달 → 파트너십 목록 생성
3) 결과를 Google Sheets에 저장 (기사 제목에서 날짜 추출 포함)
"""

import pandas as pd
import requests
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

load_dotenv()

API_KEY = os.getenv('OPENAI_API_KEY')
API_ENDPOINT = os.getenv('OPENAI_API_ENDPOINT', 'https://api.openai.com/v1/chat/completions')
GS_CRED_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
GS_SPREADSHEET_ID = os.getenv('GOOGLE_SPREADSHEET_ID', '1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8')
GS_INPUT_WORKSHEET = os.getenv('GOOGLE_INPUT_WORKSHEET', '경쟁사 동향 분석')
GS_OUTPUT_WORKSHEET = os.getenv('GOOGLE_OUTPUT_WORKSHEET', '경쟁사 협업 기업 리스트')

# LLM 분석 설정 (코드에서 직접 수정 가능)
ARTICLES_PER_CALL = 5
BATCH_SLEEP_SECONDS = 30
COMPETITOR_SLEEP_SECONDS = 10

if not API_KEY:
    raise ValueError("OPENAI_API_KEY가 .env 파일에 설정되지 않았습니다. .env.example을 참고하여 .env 파일을 생성하세요.")

COMPETITOR_BUSINESS_MAP = {
    "글루코핏": "웰다", "파스타": "웰다", "글루어트": "웰다",
    "글루어트(닥터다이어리)": "웰다", "닥터다이어리": "웰다",
    "눔": "웰다", "다노": "웰다", "필라이즈": "웰다",
    "레벨스": "웰다", "시그노스": "웰다", "뉴트리센스": "웰다", "버타": "웰다",
    "홈핏": "코어운동센터",
    "달램": "대웅헬스케어,코어운동센터",
    "파크로쉬리조트": "선마을", "더스테이힐링파크": "선마을",
    "청리움": "선마을", "오색그린야드호텔": "선마을", "깊은산속옹달샘": "선마을",
    "GC케어": "대웅헬스케어,디지털헬스케어",
    "뷰릿": "시셀", "레드밸런스": "시셀", "SNPE": "시셀",
}

def get_google_client():
    """Google Sheets 클라이언트 반환"""
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GS_CRED_FILE, scope)
    return gspread.authorize(creds)


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
            print("오류: 데이터에 '경쟁사', '제목', '본문' 컬럼이 부족합니다.")
            return None
        
        cols = required_cols.copy()
        if url_col:
            cols.append(url_col)

        df = df[cols]
        df = df[df['본문'].astype(str).str.len() > 100].reset_index(drop=True)
        
        return df

    except Exception as e:
        print(f"Google Sheets 로드 실패: {e}")
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

def extract_date_from_url(url: str):
    """URL 끝부분에서 날짜 형식 추출 (예: https://example.com/article,25.10.22)"""
    if not isinstance(url, str) or not url.strip():
        return None
    
    url_date_patterns = [
        r',(\d{2}\.\d{1,2}\.\d{1,2})(?:$|[/?#])',
        r',(\d{4}\.\d{1,2}\.\d{1,2})(?:$|[/?#])',
    ]
    
    for pattern in url_date_patterns:
        m = re.search(pattern, url)
        if m:
            date_str = m.group(1)
            normalized = normalize_date_to_yy_mm_dd(date_str)
            if normalized:
                return normalized
    
    return None


def add_article_dates(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame에 '기사 날짜' 컬럼 추가 (제목 > URL 순으로 추출)"""
    if "근거 기사 제목" not in df.columns:
        return df

    titles = []
    dates = []

    for idx, row in df.iterrows():
        title = row.get("근거 기사 제목", "")
        url = row.get("근거 기사 URL", "")

        date_str = None
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
   - 기사에 명시적으로 등장하지 않는 협력사/기관명, 협력 유형, 서비스/프로그램 이름, URL 등을 새로 만들지 마세요.
   - 제공된 JSON 안에 없는 URL을 상상해서 넣지 마세요.
   - '{competitor}'와 직접적인 협력/제휴/투자/공동사업/서비스 도입 관계가 아니라면 파트너로 포함하지 마세요.

2. **'{competitor}'와의 직접적인 관계만 파트너십으로 인정**
   - 기사에서 '{competitor}'와 어떤 회사/기관이 **협력, 제휴, 공동 연구, 공동 사업, 플랫폼 연동, 투자, 프로그램 도입(EAP 등)** 관계라고 명시된 경우에만 포함하세요.
   - 단순 비교 대상, 시장 동향 설명을 위한 예시, 경쟁 관계 설명용 회사는 파트너로 보지 마세요.

3. **대웅 사업 관점**
   - 가능하다면 **대웅의 사업('{business_name if business_name else "관련 사업"}')**과 연관된 파트너십(헬스케어/웰니스/리조트/운동센터 등)일수록 우선적으로 정리하세요.

[분석용 기사 데이터(JSON)]
다음은 '{competitor}' 관련 기사들의 목록입니다.
각 객체는 "기사 제목", "기사 본문", (있다면) "기사 URL" 필드를 포함합니다.

[데이터 시작]
{data_json}
[데이터 끝]

이제 위 JSON 데이터만을 기반으로,
아래 형식의 **CSV 문자열**을 생성하세요.

출력 형식 요구 사항 (매우 중요):

1. 출력은 **순수 CSV 텍스트만** 포함해야 합니다.
   - 코드 블록, 설명 문장, 주석, 인용구, 마크다운 표 등은 절대 포함하지 마세요.
   - 오직 CSV 행들만 출력하세요.

2. 첫 번째 줄은 반드시 **헤더**로 아래 순서를 그대로 사용합니다.
   - 번호,사업명,경쟁사,협력사/기관명,협력 유형,근거 기사 제목,근거 기사 URL

3. 각 데이터 행은 아래 의미를 가집니다.
   - 번호: 일련번호 (1부터 시작). 비워 두어도 됩니다. 나중에 시스템이 다시 번호를 매깁니다.
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

def call_llm(prompt, max_retries=10):
    """LLM API 호출 후 응답 텍스트 반환 (429 발생 시 지수 백오프 재시도)"""
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    data = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.0
    }

    for attempt in range(max_retries):
        try:
            time.sleep(0.5)

            res = requests.post(API_ENDPOINT, headers=headers, json=data, timeout=60)

            if res.status_code == 429:
                wait = 30 * (2 ** attempt)
                wait = min(wait, 600)
                print(f"429 Too Many Requests 발생 → {wait}초 후 재시도 ({attempt+1}/{max_retries})")
                time.sleep(wait)
                continue

            res.raise_for_status()

            data_json = res.json()
            content = data_json["choices"][0]["message"]["content"]
            return content.strip()
        
        except requests.exceptions.HTTPError as e:
            print(f"API 요청 실패(HTTP 오류): {e}")
            return "API 호출 실패"
        except requests.exceptions.RequestException as e:
            wait = 2 * (2 ** attempt)
            wait = min(wait, 60)
            print(f"API 요청 실패(네트워크 오류): {e} → {wait}초 후 재시도 ({attempt+1}/{max_retries})")
            time.sleep(wait)
        except Exception as e:
            print(f"LLM 응답 처리 중 오류 발생: {e}")
            return "응답 처리 실패"

    print("LLM 호출이 최대 재시도 횟수 내에 성공하지 못했습니다.")
    return "API 호출 실패"

def save_results_to_sheets(results_df, spreadsheet_id, worksheet_name):
    """결과를 Google Sheets에 저장 (기존 데이터 유지하고 이어서 추가)"""
    client = get_google_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        existing_data = worksheet.get_all_values()
        has_header = len(existing_data) > 0
    except:
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name, rows=1000, cols=10
        )
        has_header = False
    
    output_cols = ["사업명", "경쟁사", "협력사/기관명", "협력 유형", "근거 기사 제목", "근거 기사 URL", "기사 날짜"]
    
    # 헤더가 없으면 추가
    if not has_header:
        worksheet.append_row(output_cols)
    
    # 데이터 추가 (기존 데이터 아래에 이어서)
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
        
        # URL 컬럼 찾기
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
    except:
        return set()


def main():
    print("--- 1. 뉴스 데이터 로드 시작 ---")
    df_news = get_gsheet_data(GS_SPREADSHEET_ID, GS_INPUT_WORKSHEET)
    
    if df_news is None or len(df_news) == 0:
        print("분석할 데이터가 없습니다.")
        sys.exit(1)

    url_col = None
    for c in df_news.columns:
        lower = c.lower()
        if lower in ("url", "링크", "기사url", "기사 url"):
            url_col = c
            break
    
    # 이미 처리된 기사 URL 확인
    print("--- 1-1. 이미 처리된 기사 확인 중 ---")
    processed_urls = get_already_processed_urls(GS_SPREADSHEET_ID, GS_OUTPUT_WORKSHEET)
    print(f"이미 처리된 기사: {len(processed_urls)}개")
    
    # 새로운 기사만 필터링
    if url_col:
        df_news = df_news[~df_news[url_col].isin(processed_urls)].reset_index(drop=True)
    
    if len(df_news) == 0:
        print("처리할 새로운 기사가 없습니다.")
        sys.exit(0)
    
    print(f"처리할 새로운 기사: {len(df_news)}개")

    competitor_groups = df_news.groupby('경쟁사')
    print(f"총 {len(competitor_groups)}개 경쟁사 데이터 로드 완료.")
    
    all_results = []

    for competitor, full_group_df in competitor_groups:
        total_articles = len(full_group_df)
        print(f"\n[분석 시작] 경쟁사: **{competitor}** (총 {total_articles}개 기사)")

        business_name = COMPETITOR_BUSINESS_MAP.get(competitor, "")

        batch_index = 0
        for start in range(0, total_articles, ARTICLES_PER_CALL):
            end = min(start + ARTICLES_PER_CALL, total_articles)
            batch_df = full_group_df.iloc[start:end].copy()
            batch_index += 1

            print(f"  - 배치 {batch_index}: 기사 {start+1} ~ {end} 처리 중...")

            analysis_data = []
            for _, row in batch_df.iterrows():
                item = {
                    "기사 제목": row['제목'],
                    "기사 본문": row['본문'],
                }
                if url_col:
                    item["기사 URL"] = row[url_col]
                analysis_data.append(item)

            data_json = json.dumps(analysis_data, ensure_ascii=False, indent=2)
            
            prompt = make_prompt(competitor, data_json, business_name)
            csv_text = call_llm(prompt)

            if csv_text in ("API 호출 실패", "응답 처리 실패"):
                print(f"  [배치 실패] {competitor} 배치 {batch_index} - LLM 호출 문제로 인해 결과가 없습니다.")
                continue

            try:
                csv_text_stripped = csv_text.strip()
                if not csv_text_stripped:
                    print(f"  [배치 경고] {competitor} 배치 {batch_index} - 비어 있는 CSV 응답.")
                    continue

                if csv_text_stripped.startswith("```"):
                    csv_text_stripped = re.sub(r"^```[a-zA-Z]*", "", csv_text_stripped)
                    csv_text_stripped = csv_text_stripped.rstrip("`").strip()

                f = StringIO(csv_text_stripped)
                reader = csv.DictReader(f)

                fieldnames_lower = [fn.strip() for fn in reader.fieldnames] if reader.fieldnames else []
                if len(fieldnames_lower) < 6:
                    print(f"  [배치 경고] {competitor} 배치 {batch_index} - CSV 헤더 형식이 예상과 다릅니다: {fieldnames_lower}")

                row_count = 0
                batch_rows = []
                for row in reader:
                    row_count += 1
                    
                    llm_title = str(row.get("근거 기사 제목", "")).strip()
                    
                    matched_title = ""
                    matched_url = ""
                    
                    for _, orig_row in batch_df.iterrows():
                        orig_title = str(orig_row.get('제목', '')).strip()
                        if orig_title and llm_title:
                            if llm_title in orig_title or orig_title in llm_title:
                                matched_title = orig_title
                                if url_col:
                                    matched_url = str(orig_row.get(url_col, '')).strip()
                                break
                            elif len(llm_title) > 10 and len(orig_title) > 10:
                                if llm_title[:30] in orig_title or orig_title[:30] in llm_title:
                                    matched_title = orig_title
                                    if url_col:
                                        matched_url = str(orig_row.get(url_col, '')).strip()
                                    break
                    
                    if not matched_title:
                        matched_title = llm_title
                    
                    date_str = None
                    date_str, matched_title = extract_date_from_title(matched_title)
                    if date_str:
                        print(f"    [날짜 추출] 제목에서 추출: {date_str}")

                    all_results.append({
                        "사업명": business_name or row.get("사업명", ""),
                        "경쟁사": competitor,
                        "협력사/기관명": row.get("협력사/기관명", ""),
                        "협력 유형": row.get("협력 유형", ""),
                        "근거 기사 제목": matched_title,
                        "근거 기사 URL": matched_url,
                        "기사 날짜": date_str or "",
                    })

                print(f"  [배치 완료] {competitor} 배치 {batch_index} - {row_count}개 파트너십 행 수집.")

            except Exception as e:
                print(f"  [배치 CSV 파싱 오류] {competitor} 배치 {batch_index}: {e}")
                import traceback
                traceback.print_exc()
                continue

            time.sleep(BATCH_SLEEP_SECONDS)

        print(f"[경쟁사 완료] {competitor} 처리 완료. 다음 경쟁사로 넘어가기 전 {COMPETITOR_SLEEP_SECONDS}초 대기.")
        time.sleep(COMPETITOR_SLEEP_SECONDS)

    if not all_results:
        print("\n최종 수집된 파트너십 데이터가 없습니다.")
        return

    print("\n--- 3. 최종 기사 날짜 추출 및 제목 정리 ---")
    try:
        result_df = pd.DataFrame(all_results)
        print(f"수집된 데이터: {len(result_df)}개 행")
        
        result_df = add_article_dates(result_df)
        print(f"날짜 추출 완료: {result_df['기사 날짜'].notna().sum()}개 행에 날짜가 추가/확인됨")
        
        output_cols = ["사업명", "경쟁사", "협력사/기관명", "협력 유형", "근거 기사 제목", "근거 기사 URL", "기사 날짜"]
        
        for col in output_cols:
            if col not in result_df.columns:
                result_df[col] = ""
        
        # Google Sheets에 저장
        print(f"\n--- 4. Google Sheets에 결과 저장 ---")
        count = save_results_to_sheets(result_df[output_cols], GS_SPREADSHEET_ID, GS_OUTPUT_WORKSHEET)
        
        print("\n" + "="*50)
        print(result_df[output_cols].head())
        print("="*50 + "\n")
        print(f"최종 분석 결과가 Google Sheets '{GS_OUTPUT_WORKSHEET}' 시트에 저장되었습니다. (총 {count}개 행)")
        
    except Exception as e:
        print(f"최종 정리 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()