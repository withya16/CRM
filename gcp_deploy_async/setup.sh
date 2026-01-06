#!/bin/bash
# 배포 전 파일 준비 스크립트 (비동기 버전)
# 크롤링_async 폴더에서 파일을 복사합니다.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "배포 파일 준비 (비동기 버전)"
echo "=========================================="

cd "$SCRIPT_DIR"

# 크롤링_async 폴더에서 파일 복사
SOURCE_DIR="$PARENT_DIR/크롤링_async"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "✗ 크롤링_async 폴더를 찾을 수 없습니다: $SOURCE_DIR"
    exit 1
fi

echo "소스 디렉토리: $SOURCE_DIR"
echo "필요한 파일 복사 중..."

# 파이프라인 파일들
if [ -f "$SOURCE_DIR/run_pipeline.py" ]; then
    cp "$SOURCE_DIR/run_pipeline.py" .
    echo "✓ run_pipeline.py 복사 완료"
else
    echo "✗ run_pipeline.py를 찾을 수 없습니다: $SOURCE_DIR"
    exit 1
fi

if [ -f "$SOURCE_DIR/google_crawler_togooglesheet.py" ]; then
    cp "$SOURCE_DIR/google_crawler_togooglesheet.py" .
    echo "✓ google_crawler_togooglesheet.py 복사 완료"
else
    echo "✗ google_crawler_togooglesheet.py를 찾을 수 없습니다: $SOURCE_DIR"
    exit 1
fi

if [ -f "$SOURCE_DIR/competitor_llm.py" ]; then
    cp "$SOURCE_DIR/competitor_llm.py" .
    echo "✓ competitor_llm.py 복사 완료"
else
    echo "✗ competitor_llm.py를 찾을 수 없습니다: $SOURCE_DIR"
    exit 1
fi

if [ -f "$SOURCE_DIR/dart_mapping.py" ]; then
    cp "$SOURCE_DIR/dart_mapping.py" .
    echo "✓ dart_mapping.py 복사 완료"
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
