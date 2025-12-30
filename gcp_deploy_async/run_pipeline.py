#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
경쟁사 동향 분석 파이프라인 통합 실행 스크립트

1. google_crawler_togooglesheet.py - Google News 크롤링 → Google Sheets에 저장
2. competitor_llm.py - LLM 분석 → Google Sheets에 저장
3. dart_mapping.py - DART 매핑 → Google Sheets에 업데이트
"""

import sys
import traceback
from pathlib import Path

# 현재 디렉토리를 Python 경로에 추가
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# 각 스크립트 모듈 import
import google_crawler_togooglesheet
import competitor_llm
import dart_mapping


def run_pipeline():
    """전체 파이프라인 순차 실행"""
    print("=" * 60)
    print("경쟁사 동향 분석 파이프라인 시작")
    print("=" * 60)
    
    # 1단계: 크롤링
    print("\n[1/3] Google News 크롤링 시작...")
    try:
        google_crawler_togooglesheet.main()
        print("✓ 크롤링 완료\n")
    except Exception as e:
        print(f"✗ 크롤링 실패: {e}")
        traceback.print_exc()
        sys.exit(1)
    
    # 2단계: LLM 분석
    print("\n[2/3] LLM 분석 시작...")
    try:
        competitor_llm.main()
        print("✓ LLM 분석 완료\n")
    except Exception as e:
        print(f"✗ LLM 분석 실패: {e}")
        traceback.print_exc()
        sys.exit(1)
    
    # 3단계: DART 매핑
    print("\n[3/3] DART 매핑 시작...")
    try:
        # dart_mapping.py는 LLM 분석 결과('경쟁사 협업 기업 리스트')를 입력으로 받음
        import os
        os.environ['GOOGLE_INPUT_WORKSHEET'] = os.environ.get('GOOGLE_OUTPUT_WORKSHEET', '경쟁사 협업 기업 리스트')
        dart_mapping.main()
        print("✓ DART 매핑 완료\n")
    except Exception as e:
        print(f"✗ DART 매핑 실패: {e}")
        traceback.print_exc()
        sys.exit(1)
    
    print("=" * 60)
    print("전체 파이프라인 실행 완료!")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()
