#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DART 기업 리스트와 LLM 분석 결과 매핑 스크립트

1) DART API에서 전체 기업 목록(corpCode.xml)을 받아와 CSV로 캐시
2) Google Sheets의 '경쟁사 협업 기업 리스트' 시트에서 데이터 로드
3) '협력사/기관명'과 DART 기업명(corp_name)을 이름 기준으로 매핑
4) 매핑 결과(dart_corp_name)를 Google Sheets에 업데이트
"""

import os
import sys
import io
import zipfile
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from rapidfuzz import process, fuzz
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()
DART_API_KEY = os.getenv("DART_API_KEY")
DART_CORP_CSV = "dart_corp_list.csv"
GS_CRED_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
GS_SPREADSHEET_ID = os.getenv('GOOGLE_SPREADSHEET_ID', '1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8')
GS_INPUT_WORKSHEET = os.getenv('GOOGLE_INPUT_WORKSHEET', '경쟁사 협업 기업 리스트')
GS_OUTPUT_WORKSHEET = os.getenv('GOOGLE_DART_OUTPUT_WORKSHEET', '다트매핑버전')
GS_UNMATCHED_WORKSHEET = os.getenv('GOOGLE_UNMATCHED_WORKSHEET', '매핑실패기업리스트')

if not DART_API_KEY:
    raise ValueError("DART_API_KEY 가 .env 에 설정되어 있지 않습니다. (예: DART_API_KEY=발급받은키)")


def download_and_cache_dart_corp_list(force: bool = False) -> pd.DataFrame:
    """DART API에서 전체 법인 목록을 다운로드하여 CSV로 저장 후 DataFrame 반환"""
    if os.path.exists(DART_CORP_CSV) and not force:
        print(f"기존 DART 기업 리스트 CSV 로드: {DART_CORP_CSV}")
        return pd.read_csv(DART_CORP_CSV, dtype=str)

    print("DART 기업 리스트 다운로드 시작...")

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": DART_API_KEY}
    resp = requests.get(url, params=params)
    resp.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    xml_name = zf.namelist()[0]
    with zf.open(xml_name) as f:
        tree = ET.parse(f)
    root = tree.getroot()

    rows = []
    for elem in root.findall("list"):
        rows.append({
            "corp_code": elem.findtext("corp_code"),
            "corp_name": elem.findtext("corp_name"),
            "stock_code": elem.findtext("stock_code"),
            "modify_date": elem.findtext("modify_date"),
        })

    df = pd.DataFrame(rows, dtype=str)
    df.to_csv(DART_CORP_CSV, index=False, encoding="utf-8-sig")
    print(f"DART 기업 리스트 저장 완료: {DART_CORP_CSV} (총 {len(df)}개 기업)")

    return df


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
        
        if len(df) == 0:
            print(f"시트 '{worksheet_name}'에 데이터가 없습니다.")
            return None
        
        return df
    except Exception as e:
        print(f"Google Sheets 로드 실패: {e}")
        return None


def save_to_new_sheet_with_dart_mapping(spreadsheet_id, input_worksheet_name, output_worksheet_name, df):
    """기존 시트 데이터 + DART 매핑 결과를 새로운 시트에 저장"""
    client = get_google_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    
    try:
        # 기존 시트에서 데이터 읽기
        input_worksheet = spreadsheet.worksheet(input_worksheet_name)
        all_values = input_worksheet.get_all_values()
        
        if len(all_values) <= 1:
            print("업데이트할 데이터가 없습니다.")
            return 0
        
        headers = all_values[0]
        existing_df = pd.DataFrame(all_values[1:], columns=headers)
        
        # 근거 기사 제목 + 근거 기사 URL을 키로 사용하여 매칭
        def make_key(row):
            title = str(row.get('근거 기사 제목', '')).strip()
            url = str(row.get('근거 기사 URL', '')).strip()
            return f"{title}|{url}"
        
        df['match_key'] = df.apply(make_key, axis=1)
        existing_df['match_key'] = existing_df.apply(make_key, axis=1)
        
        # 매핑 딕셔너리 생성
        mapping_data = {}
        for _, row in df.iterrows():
            key = row.get('match_key', '')
            mapping_data[key] = {
                'norm_partner_name': str(row.get('norm_partner_name', '')),
                'dart_match': 'True' if row.get('dart_match') else 'False',
                'dart_corp_name': str(row.get('dart_corp_name', '')),
            }
        
        # 기존 데이터에 새 컬럼 추가
        existing_df['norm_partner_name'] = existing_df['match_key'].apply(
            lambda key: mapping_data.get(key, {}).get('norm_partner_name', '')
        )
        existing_df['dart_match'] = existing_df['match_key'].apply(
            lambda key: mapping_data.get(key, {}).get('dart_match', 'False')
        )
        existing_df['dart_corp_name'] = existing_df['match_key'].apply(
            lambda key: mapping_data.get(key, {}).get('dart_corp_name', '')
        )
        
        # match_key 컬럼 제거
        existing_df = existing_df.drop(columns=['match_key'])
        
        # 출력 시트 확인 (있으면 기존 시트 사용, 없으면 새로 생성)
        try:
            output_worksheet = spreadsheet.worksheet(output_worksheet_name)
            # 기존 시트가 있으면 데이터만 추가 (기존 데이터는 절대 삭제하지 않음)
            output_headers = list(existing_df.columns)
            # 기존 시트의 헤더 확인
            existing_output_headers = output_worksheet.row_values(1)
            
            # 기존 데이터 아래에 새 데이터 추가
            for _, row in existing_df.iterrows():
                row_values = [str(row.get(col, '')) for col in output_headers]
                output_worksheet.append_row(row_values)
            
            print(f"기존 시트 '{output_worksheet_name}'에 데이터 추가 완료 (기존 데이터 보존)")
        except:
            # 시트가 없으면 새로 생성
            output_worksheet = spreadsheet.add_worksheet(
                title=output_worksheet_name, rows=len(existing_df) + 100, cols=len(existing_df.columns) + 10
            )
            
            # 헤더 준비 (기존 헤더 + 새 컬럼들)
            output_headers = list(existing_df.columns)
            output_worksheet.append_row(output_headers)
            
            # 데이터 추가
            for _, row in existing_df.iterrows():
                row_values = [str(row.get(col, '')) for col in output_headers]
                output_worksheet.append_row(row_values)
            
            print(f"새 시트 '{output_worksheet_name}' 생성 완료")
        
        return len(existing_df)
        
    except Exception as e:
        print(f"Google Sheets 저장 실패: {e}")
        import traceback
        traceback.print_exc()
        return 0


def save_unmatched_to_sheets(spreadsheet_id, worksheet_name, unmatched_df, candidates_df):
    """매핑 실패 기업 리스트를 Google Sheets에 저장"""
    client = get_google_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        worksheet.clear()
    except:
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name, rows=1000, cols=10
        )
    
    # 후보 정보가 있으면 병합
    if candidates_df is not None and not candidates_df.empty:
        merged = unmatched_df.merge(
            candidates_df,
            on='협력사/기관명',
            how='left'
        )
        output_cols = ['협력사/기관명', 'dart_candidate_name', 'dart_candidate_code', 'candidate_score']
    else:
        merged = unmatched_df
        output_cols = ['협력사/기관명']
    
    # 헤더 추가
    worksheet.append_row(output_cols)
    
    # 데이터 추가
    for _, row in merged.iterrows():
        row_data = [str(row.get(col, '')) for col in output_cols]
        worksheet.append_row(row_data)
    
    return len(merged)


def normalize_name(name: str) -> str:
    """이름 매칭을 위한 전처리: 공백 제거 후 대문자 변환"""
    if pd.isna(name):
        return ""
    return "".join(str(name).strip().split()).upper()


def main():
    """LLM 분석 결과의 협력사명을 DART 기업 리스트와 매핑하여 DART 정보 추가"""
    print("--- 1. DART 기업 리스트 다운로드 ---")
    dart_df = download_and_cache_dart_corp_list(force=False)
    dart_df["norm_corp_name"] = dart_df["corp_name"].apply(normalize_name)

    print("\n--- 2. Google Sheets에서 데이터 로드 ---")
    print(f"입력 시트: {GS_INPUT_WORKSHEET}")
    df = get_gsheet_data(GS_SPREADSHEET_ID, GS_INPUT_WORKSHEET)
    
    if df is None or len(df) == 0:
        print("분석할 데이터가 없습니다.")
        sys.exit(1)
    
    print(f"로드된 데이터: {len(df)}개 행")
    print(f"컬럼 목록: {list(df.columns)}")

    print(f"Google Sheets 데이터 로드 완료: 총 {len(df)}행")
    
    # 이미 처리된 기사 확인 (제목 + URL 조합)
    print("\n--- 2-1. 이미 처리된 기사 확인 중 ---")
    try:
        client = get_google_client()
        spreadsheet = client.open_by_key(GS_SPREADSHEET_ID)
        output_worksheet = spreadsheet.worksheet(GS_OUTPUT_WORKSHEET)
        existing_data = output_worksheet.get_all_values()
        
        processed_keys = set()
        if len(existing_data) > 1:
            headers = existing_data[0]
            title_col_idx = None
            url_col_idx = None
            
            for idx, h in enumerate(headers):
                if h == '근거 기사 제목' or h == '근거기사제목':
                    title_col_idx = idx
                elif h == '근거 기사 URL' or h == '근거기사URL':
                    url_col_idx = idx
            
            if title_col_idx is not None and url_col_idx is not None:
                for row in existing_data[1:]:
                    if len(row) > max(title_col_idx, url_col_idx):
                        title = str(row[title_col_idx]).strip() if len(row) > title_col_idx else ''
                        url = str(row[url_col_idx]).strip() if len(row) > url_col_idx else ''
                        if title or url:
                            processed_keys.add(f"{title}|{url}")
        
        print(f"이미 처리된 기사: {len(processed_keys)}개")
        
        # 새로운 기사만 필터링
        def make_key(row):
            title = str(row.get('근거 기사 제목', '')).strip()
            url = str(row.get('근거 기사 URL', '')).strip()
            return f"{title}|{url}"
        
        df['match_key'] = df.apply(make_key, axis=1)
        df = df[~df['match_key'].isin(processed_keys)].reset_index(drop=True)
        df = df.drop(columns=['match_key'])
        
        if len(df) == 0:
            print("처리할 새로운 기사가 없습니다.")
            sys.exit(0)
        
        print(f"처리할 새로운 기사: {len(df)}개")
    except Exception as e:
        print(f"이미 처리된 기사 확인 중 오류 (처음 실행일 수 있음): {e}")
        # 오류가 나도 계속 진행

    # 컬럼 이름 매핑: '이용기업' 또는 '협력사/기관명' 모두 지원
    partner_col = None
    for col in df.columns:
        if col in ["협력사/기관명", "이용기업", "협력사기관명", "협력사 기관명"]:
            partner_col = col
            break
    
    if partner_col is None:
        print(f"\n❌ 오류: 입력 데이터에 협력사/기관명 컬럼이 없습니다.")
        print(f"현재 컬럼: {list(df.columns)}")
        print(f"\n가능한 원인:")
        print(f"1. 입력 시트('{GS_INPUT_WORKSHEET}')에 데이터가 없음")
        print(f"2. LLM 분석이 아직 실행되지 않음")
        print(f"3. 컬럼 이름이 예상과 다름 (예: '협력사/기관명', '이용기업' 등)")
        raise ValueError(f"입력 데이터에 협력사/기관명 컬럼이 없습니다. 현재 컬럼: {list(df.columns)}")
    
    # 컬럼 이름을 '협력사/기관명'으로 통일 (내부 처리용)
    if partner_col != "협력사/기관명":
        print(f"컬럼 이름 '{partner_col}'을 '협력사/기관명'으로 매핑합니다.")
        df = df.rename(columns={partner_col: "협력사/기관명"})

    df["norm_partner_name"] = df["협력사/기관명"].apply(normalize_name)

    print("\n--- 3. DART 매핑 진행 ---")
    dart_small = dart_df[["norm_corp_name", "corp_name", "corp_code", "stock_code"]].rename(
        columns={
            "corp_name": "dart_corp_name",
            "corp_code": "dart_corp_code",
            "stock_code": "dart_stock_code",
        }
    )

    merged = df.merge(
        dart_small,
        left_on="norm_partner_name",
        right_on="norm_corp_name",
        how="left",
    )

    merged["dart_match"] = merged["dart_corp_name"].notna()
    
    # dart_corp_name이 매칭된 경우, 협력사/기관명을 DART 공식 명칭으로 업데이트
    merged.loc[merged["dart_match"], "협력사/기관명"] = merged.loc[merged["dart_match"], "dart_corp_name"]
    
    # None 값을 빈 문자열로 변환
    merged["dart_corp_name"] = merged["dart_corp_name"].fillna("")

    matched_count = merged['dart_match'].sum()
    print(f"DART 매핑 완료: {matched_count}개 매칭 성공 / {len(merged)}개 전체")
    
    if matched_count > 0:
        print("\n매칭된 예시 5개:")
        matched_samples = merged[merged["dart_match"]][["협력사/기관명", "dart_corp_name"]].head()
        print(matched_samples)

    print("\n--- 4. Google Sheets에 결과 저장 (새 시트 생성) ---")
    save_count = save_to_new_sheet_with_dart_mapping(GS_SPREADSHEET_ID, GS_INPUT_WORKSHEET, GS_OUTPUT_WORKSHEET, merged)
    print(f"새 시트 '{GS_OUTPUT_WORKSHEET}' 저장 완료: {save_count}개 행")

    unmatched = merged[~merged["dart_match"]].copy()
    if not unmatched.empty:
        unmatched_partners = (
            unmatched["협력사/기관명"]
            .dropna()
            .drop_duplicates()
            .sort_values()
            .reset_index(drop=True)
        )
        
        unmatched_df = pd.DataFrame({"협력사/기관명": unmatched_partners})
        print(f"\ndart_match=False 인 협력사 {len(unmatched_df)}개 발견")

        candidates_df = build_fuzzy_candidates_for_unmatched(unmatched_partners, dart_df)
        
        print("\n--- 5. 매핑 실패 기업 리스트를 Google Sheets에 저장 ---")
        save_count = save_unmatched_to_sheets(GS_SPREADSHEET_ID, GS_UNMATCHED_WORKSHEET, unmatched_df, candidates_df)
        print(f"매핑 실패 기업 리스트 저장 완료: {save_count}개 (시트: {GS_UNMATCHED_WORKSHEET})")
        print("candidate_score 90 이상인 항목을 수동으로 확인하세요.")
    else:
        print("\n모든 협력사가 DART 기업 리스트와 매칭되었습니다.")

def build_fuzzy_candidates_for_unmatched(unmatched_names: pd.Series, dart_df: pd.DataFrame) -> pd.DataFrame:
    """매칭 실패한 협력사 이름에 대해 Fuzzy 매칭으로 유사한 DART 기업명 후보 추천"""
    choices = dart_df["corp_name"].tolist()
    results = []

    for name in unmatched_names:
        if not isinstance(name, str) or not name.strip():
            results.append((name, "", "", 0))
            continue

        match = process.extractOne(name, choices, scorer=fuzz.WRatio)
        if match:
            cand_name, score, idx = match
            results.append((name, cand_name, dart_df.iloc[idx]["corp_code"], score))
        else:
            results.append((name, "", "", 0))

    return pd.DataFrame(
        results,
        columns=["협력사/기관명", "dart_candidate_name", "dart_candidate_code", "candidate_score"],
    )

if __name__ == "__main__":
    main()