#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DART 기업 리스트와 LLM 분석 결과 매핑 스크립트

1) DART API에서 전체 기업 목록(corpCode.xml)을 받아와 CSV로 캐시
2) Google Sheets의 '경쟁사 협업 기업 리스트' 시트에서 데이터 로드
3) '협력사/기관명'과 DART 기업명(corp_name)을 이름 기준으로 매핑
4) 매핑 결과를 출력 시트(다트매핑버전)에 저장

[요구 반영]
- 입력 시트(경쟁사 협업 기업 리스트)는 절대 수정하지 않음 (읽기만)
- 출력 시트(다트매핑버전)에는 "입력 시트 원본 컬럼들 + 3개 컬럼 추가" 형태로 append 저장:
  norm_partner_name, dart_match(TRUE/FALSE), dart_corp_name
- 매핑 실패 기업 리스트는 '매핑실패기업리스트' 시트에 append 저장 (clear 금지)
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

GS_CRED_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GS_SPREADSHEET_ID = os.getenv(
    "GOOGLE_SPREADSHEET_ID",
    "1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8"
)
GS_INPUT_WORKSHEET = os.getenv("GOOGLE_INPUT_WORKSHEET", "경쟁사 협업 기업 리스트")
GS_OUTPUT_WORKSHEET = os.getenv("GOOGLE_DART_OUTPUT_WORKSHEET", "다트매핑버전")

# 매핑 실패 기업 리스트는 무조건 이 시트로 append 저장
GS_UNMATCHED_WORKSHEET = "매핑실패기업리스트"

# 출력에 추가할 3개 컬럼(고정)
ADD_COLS = ["norm_partner_name", "dart_match", "dart_corp_name"]

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
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
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


def save_to_new_sheet_with_dart_mapping(spreadsheet_id, output_worksheet_name, df):
    """
    출력 시트에 결과를 append 저장 (기존 데이터 유지, 새 데이터만 추가)
    - df는 "입력시트 컬럼들 + 3개 컬럼" 형태로 이미 만들어져 있어야 함
    """
    client = get_google_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        if df is None or len(df) == 0:
            print("저장할 데이터가 없습니다.")
            return 0

        # 출력 시트 확인 (있으면 기존 시트 사용, 없으면 새로 생성)
        try:
            output_worksheet = spreadsheet.worksheet(output_worksheet_name)
            print(f"기존 시트 '{output_worksheet_name}' 발견")
        except Exception:
            output_worksheet = spreadsheet.add_worksheet(
                title=output_worksheet_name,
                rows=len(df) + 100,
                cols=len(df.columns) + 10
            )
            print(f"새 시트 '{output_worksheet_name}' 생성 완료")

        output_headers = list(df.columns)

        # 헤더 처리
        existing_output_headers = []
        try:
            existing_output_headers = output_worksheet.row_values(1)
        except Exception:
            existing_output_headers = []

        if not existing_output_headers:
            output_worksheet.append_row(output_headers)
        else:
            # 헤더가 있는데 구조가 달라졌으면 1행 헤더를 갱신(데이터는 유지)
            if existing_output_headers != output_headers:
                print("주의: 출력 시트 헤더가 현재 df 헤더와 달라서, 1행 헤더를 갱신합니다.")
                output_worksheet.resize(rows=output_worksheet.row_count, cols=len(output_headers))
                output_worksheet.update("A1", [output_headers])

        # 데이터를 배치로 추가 (한 번에 최대 500행씩)
        batch_size = 500
        rows_to_add = []
        for _, row in df.iterrows():
            row_values = [str(row.get(col, "")) for col in output_headers]
            rows_to_add.append(row_values)

            if len(rows_to_add) >= batch_size:
                output_worksheet.append_rows(rows_to_add)
                rows_to_add = []

        if rows_to_add:
            output_worksheet.append_rows(rows_to_add)

        print(f"시트 '{output_worksheet_name}'에 데이터 추가 완료: {len(df)}개 행")
        return len(df)

    except Exception as e:
        print(f"Google Sheets 저장 실패: {e}")
        import traceback
        traceback.print_exc()
        return 0


def save_unmatched_to_sheets(spreadsheet_id, worksheet_name, unmatched_df, candidates_df):
    """매핑 실패 기업 리스트를 Google Sheets에 'append'로 저장 (clear 없음)"""
    client = get_google_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    # 시트 없으면 생성, 있으면 그대로 사용
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=10)

    # 저장할 데이터 구성
    if candidates_df is not None and not candidates_df.empty:
        merged = unmatched_df.merge(candidates_df, on="협력사/기관명", how="left")
        output_cols = ["협력사/기관명", "dart_candidate_name", "dart_candidate_code", "candidate_score"]
    else:
        merged = unmatched_df
        output_cols = ["협력사/기관명"]

    # 헤더가 아예 없으면 1회만 추가 (append 모드 유지)
    existing_headers = []
    try:
        existing_headers = worksheet.row_values(1)
    except Exception:
        existing_headers = []

    if not existing_headers:
        worksheet.append_row(output_cols)

    # 데이터 append
    batch_size = 500
    rows_to_add = []
    for _, row in merged.iterrows():
        row_data = [str(row.get(col, "")) for col in output_cols]
        rows_to_add.append(row_data)

        if len(rows_to_add) >= batch_size:
            worksheet.append_rows(rows_to_add)
            rows_to_add = []

    if rows_to_add:
        worksheet.append_rows(rows_to_add)

    return len(merged)


def normalize_name(name: str) -> str:
    """이름 매칭을 위한 전처리: 공백 제거 후 대문자 변환"""
    if pd.isna(name):
        return ""
    return "".join(str(name).strip().split()).upper()


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


def main():
    """
    입력 시트의 협력사명을 DART 기업 리스트와 매핑하여
    출력 시트(다트매핑버전)에 "입력시트 컬럼 + 3개 컬럼" 형태로 append 저장
    """
    input_worksheet = os.getenv("GOOGLE_INPUT_WORKSHEET", GS_INPUT_WORKSHEET)
    output_worksheet = os.getenv("GOOGLE_DART_OUTPUT_WORKSHEET", GS_OUTPUT_WORKSHEET)
    unmatched_worksheet = GS_UNMATCHED_WORKSHEET

    # dart_mapping.py는 항상 이 시트를 입력으로 받음
    if input_worksheet == "경쟁사 동향 분석":
        input_worksheet = "경쟁사 협업 기업 리스트"
        print("주의: 입력 시트를 '경쟁사 동향 분석'에서 '경쟁사 협업 기업 리스트'로 자동 변경했습니다.")

    print("--- 1. DART 기업 리스트 다운로드 ---")
    dart_df = download_and_cache_dart_corp_list(force=False)
    dart_df["norm_corp_name"] = dart_df["corp_name"].apply(normalize_name)

    print("\n--- 2. Google Sheets에서 데이터 로드 ---")
    print(f"입력 시트: {input_worksheet}")
    df = get_gsheet_data(GS_SPREADSHEET_ID, input_worksheet)

    if df is None or len(df) == 0:
        print("분석할 데이터가 없습니다.")
        sys.exit(1)

    print(f"로드된 데이터: {len(df)}개 행")
    print(f"컬럼 목록: {list(df.columns)}")

    # 컬럼 이름 매핑: '이용기업' 또는 '협력사/기관명' 모두 지원
    partner_col = None
    for col in df.columns:
        if col in ["협력사/기관명", "이용기업", "협력사기관명", "협력사 기관명"]:
            partner_col = col
            break

    if partner_col is None:
        raise ValueError(f"입력 데이터에 협력사/기관명 컬럼이 없습니다. 현재 컬럼: {list(df.columns)}")

    if partner_col != "협력사/기관명":
        print(f"컬럼 이름 '{partner_col}'을 '협력사/기관명'으로 매핑합니다.")
        df = df.rename(columns={partner_col: "협력사/기관명"})

    # ✅ 출력시트에 "원래 입력시트 + 3개 컬럼"이 되도록,
    #    입력 원본 컬럼들을 먼저 확정(추가 컬럼 제외)
    base_cols = [c for c in df.columns if c not in ADD_COLS]

    # 새로 추가되는 컬럼
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

    merged["dart_match_bool"] = merged["dart_corp_name"].notna()

    # 매칭된 경우 협력사/기관명을 DART 공식 명칭으로 변경 (기존 동작 유지)
    merged.loc[merged["dart_match_bool"], "협력사/기관명"] = merged.loc[merged["dart_match_bool"], "dart_corp_name"]

    # 결측치 처리
    merged["dart_corp_name"] = merged["dart_corp_name"].fillna("")

    matched_count = int(merged["dart_match_bool"].sum())
    print(f"DART 매핑 완료: {matched_count}개 매칭 성공 / {len(merged)}개 전체")

    unmatched = merged[~merged["dart_match_bool"]].copy()

    # 저장용 TRUE/FALSE 문자열 변환
    merged["dart_match"] = merged["dart_match_bool"].map({True: "TRUE", False: "FALSE"})

    # ✅ 출력 시트 저장: 입력시트 원본 컬럼 + 3개 컬럼
    output_cols = base_cols + ADD_COLS
    merged_to_save = merged[output_cols].copy()

    print("\n--- 4. Google Sheets에 결과 저장(출력 시트 append) ---")
    save_count = save_to_new_sheet_with_dart_mapping(GS_SPREADSHEET_ID, output_worksheet, merged_to_save)
    print(f"시트 '{output_worksheet}' 저장 완료: {save_count}개 행")

    if not unmatched.empty:
        unmatched_partners = (
            unmatched["협력사/기관명"]
            .dropna()
            .drop_duplicates()
            .sort_values()
            .reset_index(drop=True)
        )

        unmatched_df = pd.DataFrame({"협력사/기관명": unmatched_partners})
        print(f"\ndart_match=FALSE 인 협력사 {len(unmatched_df)}개 발견")

        candidates_df = build_fuzzy_candidates_for_unmatched(unmatched_partners, dart_df)

        print("\n--- 5. 매핑 실패 기업 리스트를 Google Sheets에 append 저장 ---")
        save_count = save_unmatched_to_sheets(GS_SPREADSHEET_ID, unmatched_worksheet, unmatched_df, candidates_df)
        print(f"매핑 실패 기업 리스트 저장 완료: {save_count}개 (시트: {unmatched_worksheet})")
        print("candidate_score 90 이상인 항목을 수동으로 확인하세요.")
    else:
        print("\n모든 협력사가 DART 기업 리스트와 매칭되었습니다.")


if __name__ == "__main__":
    main()