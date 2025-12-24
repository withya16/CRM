#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloud Run Job 진입점
run_pipeline.py를 실행하고 Secret Manager에서 환경 변수 로드
"""

import os
import sys
import json
import base64
from google.cloud import secretmanager


def get_secret(secret_id):
    """Secret Manager에서 시크릿 가져오기"""
    try:
        client = secretmanager.SecretManagerServiceClient()
        project_id = os.environ.get('GCP_PROJECT_ID')
        if not project_id:
            project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
        
        if not project_id:
            raise ValueError("GCP_PROJECT_ID 환경 변수가 설정되지 않았습니다.")
        
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Secret {secret_id} 가져오기 실패: {e}")
        raise


def setup_environment():
    """환경 변수 설정"""
    # GCP 프로젝트 ID
    project_id = os.environ.get('GCP_PROJECT_ID')
    if not project_id:
        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
    
    if not project_id:
        raise ValueError("GCP_PROJECT_ID 환경 변수가 설정되지 않았습니다.")
    
    os.environ['GCP_PROJECT_ID'] = project_id
    print(f"GCP 프로젝트 ID: {project_id}")
    
    # Secret Manager에서 시크릿 가져오기
    print("Secret Manager에서 시크릿 가져오는 중...")
    
    try:
        # OpenAI API 키
        openai_key = get_secret('OPENAI_API_KEY')
        os.environ['OPENAI_API_KEY'] = openai_key
        print("✓ OPENAI_API_KEY 로드 완료")
    except Exception as e:
        print(f"✗ OPENAI_API_KEY 로드 실패: {e}")
        raise
    
    try:
        # DART API 키
        dart_key = get_secret('DART_API_KEY')
        os.environ['DART_API_KEY'] = dart_key
        print("✓ DART_API_KEY 로드 완료")
    except Exception as e:
        print(f"✗ DART_API_KEY 로드 실패: {e}")
        raise
    
    try:
        # Google Spreadsheet ID
        spreadsheet_id = get_secret('GOOGLE_SPREADSHEET_ID')
        os.environ['GOOGLE_SPREADSHEET_ID'] = spreadsheet_id
        print("✓ GOOGLE_SPREADSHEET_ID 로드 완료")
    except Exception as e:
        print(f"✗ GOOGLE_SPREADSHEET_ID 로드 실패: {e}")
        raise
    
    try:
        # Google Credentials JSON 처리
        creds_json_b64 = get_secret('GOOGLE_CREDENTIALS_JSON')
        creds_json = base64.b64decode(creds_json_b64).decode('utf-8')
        # 임시 파일로 저장
        creds_path = '/tmp/credentials.json'
        with open(creds_path, 'w') as f:
            f.write(creds_json)
        os.environ['GOOGLE_CREDENTIALS_FILE'] = creds_path
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
        print("✓ GOOGLE_CREDENTIALS_JSON 로드 완료")
    except Exception as e:
        print(f"✗ GOOGLE_CREDENTIALS_JSON 로드 실패: {e}")
        raise
    
    # 기본값 설정 (시트 이름 등)
    if not os.environ.get('GOOGLE_INPUT_WORKSHEET'):
        os.environ['GOOGLE_INPUT_WORKSHEET'] = '경쟁사 동향 분석'
    if not os.environ.get('GOOGLE_OUTPUT_WORKSHEET'):
        os.environ['GOOGLE_OUTPUT_WORKSHEET'] = '경쟁사 협업 기업 리스트'
    if not os.environ.get('GOOGLE_DART_OUTPUT_WORKSHEET'):
        os.environ['GOOGLE_DART_OUTPUT_WORKSHEET'] = '경쟁사 협업 기업 리스트_with_dart'
    if not os.environ.get('GOOGLE_UNMATCHED_WORKSHEET'):
        os.environ['GOOGLE_UNMATCHED_WORKSHEET'] = '매핑실패기업리스트'
    if not os.environ.get('GOOGLE_CRAWL_WORKSHEET'):
        os.environ['GOOGLE_CRAWL_WORKSHEET'] = '경쟁사 동향 분석'
    
    print("환경 변수 설정 완료")


def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("GCP Cloud Run Job - 경쟁사 동향 분석 파이프라인")
    print("=" * 60)
    
    # 환경 변수 설정
    try:
        setup_environment()
    except Exception as e:
        print(f"환경 변수 설정 실패: {e}")
        sys.exit(1)
    
    # run_pipeline 모듈 import 및 실행
    try:
        # 현재 디렉토리를 경로에 추가
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, current_dir)
        
        print("\n파이프라인 실행 시작...")
        # run_pipeline 실행
        from run_pipeline import run_pipeline
        run_pipeline()
        
        print("=" * 60)
        print("Cloud Run Job 완료")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        print(f"\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()




