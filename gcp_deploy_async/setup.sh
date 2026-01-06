#!/bin/bash
# 배포 전 파일 준비 스크립트

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "배포 파일 준비"
echo "=========================================="

cd "$SCRIPT_DIR"

# 필요한 파일들 복사
echo "필요한 파일 복사 중..."

# 파이프라인 파일들 (일반 버전)
SOURCE_DIR="$PARENT_DIR"

# 필요한 파일들 복사
echo "필요한 파일 복사 중..."

# 파이프라인 파일들
if [ -f "$SOURCE_DIR/run_pipeline.py" ]; then
    cp "$SOURCE_DIR/run_pipeline.py" .
    echo "✓ run_pipeline.py 복사 완료 ($SOURCE_DIR)"
else
    echo "✗ run_pipeline.py를 찾을 수 없습니다: $SOURCE_DIR"
    exit 1
fi

if [ -f "$SOURCE_DIR/google_crawler_togooglesheet.py" ]; then
    cp "$SOURCE_DIR/google_crawler_togooglesheet.py" .
    echo "✓ google_crawler_togooglesheet.py 복사 완료 ($SOURCE_DIR)"
else
    echo "✗ google_crawler_togooglesheet.py를 찾을 수 없습니다: $SOURCE_DIR"
    exit 1
fi

if [ -f "$SOURCE_DIR/competitor_llm.py" ]; then
    cp "$SOURCE_DIR/competitor_llm.py" .
    echo "✓ competitor_llm.py 복사 완료 ($SOURCE_DIR)"
else
    echo "✗ competitor_llm.py를 찾을 수 없습니다: $SOURCE_DIR"
    exit 1
fi

if [ -f "$SOURCE_DIR/dart_mapping.py" ]; then
    cp "$SOURCE_DIR/dart_mapping.py" .
    echo "✓ dart_mapping.py 복사 완료 ($SOURCE_DIR)"
else
    echo "✗ dart_mapping.py를 찾을 수 없습니다: $SOURCE_DIR"
    exit 1
fi

echo ""
echo "=========================================="
echo "파일 준비 완료!"
echo "=========================================="
echo ""
echo "다음 단계:"
echo "1. Secret Manager에 시크릿 저장"
echo "2. ./deploy.sh 실행"
echo "=========================================="
