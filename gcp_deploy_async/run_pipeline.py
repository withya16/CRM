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


def run_pipeline_with_stages(run_stages=None):
    """파이프라인 단계별 실행 (선택적으로 특정 단계만 실행 가능)"""
    if run_stages is None:
        run_stages = ['crawl', 'llm', 'dart']
    
    print("=" * 60)
    print("경쟁사 동향 분석 파이프라인 시작")
    print(f"실행 단계: {', '.join(run_stages)}")
    print("=" * 60)
    
    step_num = 1
    total_steps = len(run_stages)
    
    # 1단계: 크롤링
    if 'crawl' in run_stages:
        print(f"\n[{step_num}/{total_steps}] Google News 크롤링 시작...")
        try:
            google_crawler_togooglesheet.main()
            print("✓ 크롤링 완료\n")
        except Exception as e:
            print(f"✗ 크롤링 실패: {e}")
            traceback.print_exc()
            sys.exit(1)
        step_num += 1
    
    # 2단계: LLM 분석
    if 'llm' in run_stages:
        print(f"\n[{step_num}/{total_steps}] LLM 분석 시작...")
        try:
            competitor_llm.main()
            print("✓ LLM 분석 완료\n")
        except Exception as e:
            print(f"✗ LLM 분석 실패: {e}")
            traceback.print_exc()
            sys.exit(1)
        step_num += 1
    
    # 3단계: DART 매핑
    if 'dart' in run_stages:
        print(f"\n[{step_num}/{total_steps}] DART 매핑 시작...")
        try:
            dart_mapping.main()
            print("✓ DART 매핑 완료\n")
        except Exception as e:
            print(f"✗ DART 매핑 실패: {e}")
            traceback.print_exc()
            sys.exit(1)
        step_num += 1
    
    print("=" * 60)
    print(f"파이프라인 실행 완료! (실행된 단계: {', '.join(run_stages)})")
    print("=" * 60)


def run_pipeline():
    """전체 파이프라인 순차 실행 (하위 호환성)"""
    run_pipeline_with_stages(['crawl', 'llm', 'dart'])


if __name__ == "__main__":
    run_pipeline()
