#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DART 기업 리스트와 LLM 분석 결과 매핑 스크립트

1) DART API에서 전체 기업 목록(corpCode.xml)을 받아와 CSV로 캐시
2) Google Sheets의 LLM 분석 결과 시트에서 데이터 로드
3) '협력사/기관명'과 DART 기업명(corp_name)을 이름 기준으로 매핑
4) 매핑 결과를 출력 시트에 저장

"""

# ============================================================================
# 시트 이름 설정 (필요시 여기서 수정)
# ============================================================================
GS_INPUT_WORKSHEET = "[LLM] 경쟁사 협업 기업 분석"
GS_OUTPUT_WORKSHEET = "[DART] 기업명 맵핑"

import os
import sys
import io
import zipfile
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
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
# 시트 이름은 파일 상단에서 설정됨 (GS_INPUT_WORKSHEET, GS_OUTPUT_WORKSHEET)

# 출력에 추가할 3개 컬럼(고정)
ADD_COLS = ["norm_partner_name", "dart_match", "dart_corp_name"]

# 출력 시트 컬럼 순서 (명시적으로 지정)
OUTPUT_COLUMN_ORDER = [
    "사업명",
    "경쟁사",
    "협력사/기관명",
    "협력 유형",
    "근거 기사 제목",
    "근거 기사 URL",
    "기사 날짜",
    "norm_partner_name",
    "dart_match",
    "dart_corp_name"
]

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
    """Google Sheets 데이터를 Pandas DataFrame으로 로드 (status가 DONE이 아닌 행만)"""
    try:
        client = get_google_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        all_data = worksheet.get_all_values()
        
        if len(all_data) <= 1:
            print(f"시트 '{worksheet_name}'에 데이터가 없습니다.")
            return None, None, []
        
        headers = all_data[0]
        df = pd.DataFrame(all_data[1:], columns=headers)
        
        # 행 번호 추가 (시트의 실제 행 번호, 2부터 시작)
        df['_sheet_row_num'] = range(2, 2 + len(df))
        
        # status 컬럼 확인
        status_col = None
        for col in df.columns:
            if col.lower() == 'status':
                status_col = col
                break
        
        # status 필터링: DONE이 아닌 것만 처리
        if status_col and status_col in df.columns:
            df['_status_upper'] = df[status_col].astype(str).str.strip().str.upper()
            original_count = len(df)
            df = df[df['_status_upper'] != 'DONE'].reset_index(drop=True)
            df = df.drop(columns=['_status_upper'], errors='ignore')
            filtered_count = len(df)
            print(f"status 필터링: {original_count}개 중 {filtered_count}개 처리 대상 (DONE 제외)")
        else:
            print(f"경고: '{worksheet_name}' 시트에 status 컬럼이 없습니다. 모든 행을 처리합니다.")
        
        if len(df) == 0:
            print(f"처리할 데이터가 없습니다 (모두 DONE 상태 또는 데이터 없음).")
            return None, None, []

        return df, worksheet, df['_sheet_row_num'].tolist()
    except Exception as e:
        print(f"Google Sheets 로드 실패: {e}")
        import traceback
        traceback.print_exc()
        return None, None, []


def save_to_new_sheet_with_dart_mapping(spreadsheet_id, output_worksheet_name, df):
    """
    출력 시트에 결과를 append 저장 (기존 데이터 유지, 새 데이터만 추가)
    - df는 "입력시트 컬럼들 + 3개 컬럼" 형태로 이미 만들어져 있어야 함
    - 기존 시트 헤더와 DataFrame 컬럼이 다르면 DataFrame 컬럼 기준으로 저장
    """
    client = get_google_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        if df is None or len(df) == 0:
            print("저장할 데이터가 없습니다.")
            return 0

        # DataFrame 컬럼 (저장할 데이터의 컬럼)
        df_columns = list(df.columns)

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

        # 기존 시트의 헤더 가져오기
        existing_headers = []
        try:
            existing_headers = output_worksheet.row_values(1)
        except Exception:
            existing_headers = []

        # 헤더 결정
        if not existing_headers:
            # 헤더가 없으면 DataFrame 컬럼으로 새로 생성
            output_worksheet.update('A1', [df_columns])
            output_headers = df_columns
            print(f"  새 헤더 생성: {df_columns}")
        elif existing_headers == df_columns:
            # 기존 헤더와 동일하면 그대로 사용
            output_headers = existing_headers
        else:
            # 기존 헤더와 다르면 DataFrame 컬럼 기준으로 저장
            # (기존 데이터와 컬럼 불일치 발생 가능 - 경고 출력)
            print(f"  경고: 기존 헤더({len(existing_headers)}개)와 새 데이터 컬럼({len(df_columns)}개)이 다릅니다.")
            print(f"  기존 헤더: {existing_headers[:5]}...")
            print(f"  새 컬럼: {df_columns[:5]}...")
            print(f"  DataFrame 컬럼 순서대로 데이터를 저장합니다.")
            output_headers = df_columns

        # 데이터를 배치로 추가 (한 번에 최대 500행씩)
        batch_size = 500
        rows_to_add = []
        for _, row in df.iterrows():
            # DataFrame 컬럼 순서대로 데이터 구성
            row_values = []
            for col_name in output_headers:
                if col_name in df.columns:
                    value = row.get(col_name, "")
                    # NaN 처리
                    if pd.isna(value):
                        value = ""
                    else:
                        value = str(value).strip()
                else:
                    value = ""
                row_values.append(value)
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


def normalize_name(name: str) -> str:
    """이름 매칭을 위한 전처리: 공백 제거 후 대문자 변환"""
    if pd.isna(name):
        return ""
    return "".join(str(name).strip().split()).upper()


def get_column_letter(col_num):
    """컬럼 번호를 A1 표기법의 열 문자로 변환 (1-based)"""
    result = ""
    while col_num > 0:
        col_num -= 1
        result = chr(65 + (col_num % 26)) + result
        col_num //= 26
    return result


def update_input_sheet_status(worksheet, row_numbers, status_value):
    """입력 시트의 특정 행들의 status 컬럼을 DONE으로 업데이트
    
    Args:
        worksheet: gspread worksheet 객체
        row_numbers: 시트 행 번호 리스트 (헤더 제외, 2부터 시작하는 실제 행 번호)
        status_value: 업데이트할 status 값 (DONE)
    """
    try:
        if not row_numbers:
            return
        
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
            print(f"입력 시트 status 업데이트: {len(updates)}개 행을 '{status_value}'로 업데이트")
        
    except Exception as e:
        print(f"입력 시트 status 업데이트 오류: {e}")
        import traceback
        traceback.print_exc()


def main():
    """
    입력 시트의 협력사명을 DART 기업 리스트와 매핑하여
    출력 시트에 "입력시트 컬럼 + 3개 컬럼" 형태로 append 저장
    """
    input_worksheet = GS_INPUT_WORKSHEET
    output_worksheet = GS_OUTPUT_WORKSHEET

    print("--- 1. DART 기업 리스트 다운로드 ---")
    dart_df = download_and_cache_dart_corp_list(force=False)
    dart_df["norm_corp_name"] = dart_df["corp_name"].apply(normalize_name)

    print("\n--- 2. Google Sheets에서 데이터 로드 ---")
    print(f"입력 시트: {input_worksheet}")
    df, input_worksheet_obj, processed_row_numbers = get_gsheet_data(GS_SPREADSHEET_ID, input_worksheet)

    if df is None or len(df) == 0:
        print("처리할 데이터가 없습니다 (모두 DONE 상태 또는 데이터 없음).")
        sys.exit(0)

    print(f"로드된 데이터: {len(df)}개 행 (status가 DONE이 아닌 행만)")
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

    # 출력시트에 "원래 입력시트 + 3개 컬럼"이 되도록,
    #    입력 원본 컬럼들을 먼저 확정(추가 컬럼 및 내부 컬럼 제외)
    base_cols = [c for c in df.columns if c not in ADD_COLS and not c.startswith('_')]

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

    # 출력 시트 저장: 지정된 컬럼 순서로 재정렬
    # OUTPUT_COLUMN_ORDER에 있는 컬럼만 선택하고, 없는 컬럼은 빈 값으로 추가
    output_cols = []
    for col in OUTPUT_COLUMN_ORDER:
        if col in merged.columns:
            output_cols.append(col)
        else:
            # 없는 컬럼은 빈 값으로 추가
            merged[col] = ""
            output_cols.append(col)
            print(f"경고: '{col}' 컬럼이 입력 데이터에 없어 빈 값으로 추가합니다.")
    
    merged_to_save = merged[output_cols].copy()

    print("\n--- 4. Google Sheets에 결과 저장(출력 시트 append) ---")
    save_count = save_to_new_sheet_with_dart_mapping(GS_SPREADSHEET_ID, output_worksheet, merged_to_save)
    print(f"시트 '{output_worksheet}' 저장 완료: {save_count}개 행")
    
    unmatched_count = len(unmatched) if not unmatched.empty else 0
    if unmatched_count > 0:
        print(f"\n매핑 실패한 협력사: {unmatched_count}개 (dart_match=FALSE)")
    else:
        print("\n모든 협력사가 DART 기업 리스트와 매칭되었습니다.")
    
    # 처리 완료 후 입력 시트의 status를 DONE으로 업데이트
    print("\n--- 5. 입력 시트 status 업데이트 (DONE) ---")
    if input_worksheet_obj and processed_row_numbers:
        update_input_sheet_status(input_worksheet_obj, processed_row_numbers, 'DONE')
        print(f"처리 완료: {len(processed_row_numbers)}개 행의 status를 DONE으로 업데이트했습니다.")
    else:
        print("입력 시트 정보가 없어 status를 업데이트할 수 없습니다.")


if __name__ == "__main__":
    main()