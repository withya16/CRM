#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구글 뉴스 크롤러 - 구글시트 업로드 버전 (비동기 처리)

지난 1주일 기사만 크롤링하여 구글 시트에 추가
- 구글 검색 결과 추출: Selenium 사용 (순차 처리, 차단 방지)
- 기사 본문 크롤링: aiohttp 사용 (비동기 처리, 동시 요청 수 제한)

차단 방지:
- Semaphore로 동시 요청 수 제한 (MAX_CONCURRENT_REQUESTS = 5)
- 각 요청 사이 딜레이 유지 (0.3초)
- 구글 검색은 순차 처리 유지
"""

# ============================================================================
# 시트 이름 설정 (필요시 여기서 수정)
# ============================================================================
GOOGLE_SHEET_NAME = "[크롤링] 경쟁사 기사 수집"

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import os
import stat
import subprocess
import platform
from urllib.parse import quote
import asyncio
import aiohttp

try:
    import gspread
    from google.oauth2.service_account import Credentials
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False
    print("경고: gspread가 설치되지 않았습니다.")

COMPETITORS = [
    "글루코핏", "파스타", "글루어트", "닥터다이어리", "눔", "다노", "필라이즈",
    "레벨스", "시그노스", "뉴트리센스", "버타", "홈핏", "달램", "파크로쉬리조트",
    "더스테이힐링파크", "청리움", "오색그린야드호텔", "깊은산속옹달샘", "GC케어",
    "뷰핏", "레드밸런스", "SNPE", "헬스맥스", "애니핏플러스"
]

KEYWORDS = ["도입", "협약", "협업", "제휴"]

MAX_ARTICLES_PER_QUERY = 20
MAX_PAGES = 2

# 비동기 처리 설정 (차단 방지)
MAX_CONCURRENT_REQUESTS = 5  # 동시 요청 수 제한

from dotenv import load_dotenv
load_dotenv()


def setup_driver():
    """Chrome 드라이버 초기화"""
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--headless')
    options.page_load_strategy = 'eager'
    
    try:
        driver_path = ChromeDriverManager().install()
        if os.path.exists(driver_path):
            os.chmod(driver_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
            # macOS에서만 xattr 명령어 실행 (Linux에서는 필요 없음)
            if platform.system() == 'Darwin':  # macOS
                try:
                    subprocess.run(
                        ['xattr', '-d', 'com.apple.quarantine', driver_path],
                        stderr=subprocess.DEVNULL,
                        check=False
                    )
                except (FileNotFoundError, subprocess.SubprocessError):
                    # xattr 명령어가 없거나 실패해도 계속 진행
                    pass
        
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(20)
        return driver
    except Exception as e:
        print(f"드라이버 설정 오류: {e}")
        return None


def search_google_news_recent(driver, query):
    """구글 뉴스 검색 (지난 1주일)"""
    try:
        url = f"https://www.google.com/search?q={quote(query)}&tbm=nws&tbs=qdr:w"
        driver.get(url)
        time.sleep(3)
        return True
    except Exception:
        return False


def parse_relative_date(date_text):
    """상대 날짜 텍스트를 YY.MM.DD 형식으로 변환"""
    from datetime import datetime, timedelta
    import re

    if not date_text:
        return ""

    date_text = date_text.strip()
    today = datetime.now()

    # "X시간 전", "X분 전" -> 오늘 날짜
    if re.search(r'\d+\s*(시간|분)\s*전', date_text):
        return today.strftime('%y.%m.%d')

    # "X일 전"
    match = re.search(r'(\d+)\s*일\s*전', date_text)
    if match:
        days = int(match.group(1))
        target_date = today - timedelta(days=days)
        return target_date.strftime('%y.%m.%d')

    # "X주 전"
    match = re.search(r'(\d+)\s*주\s*전', date_text)
    if match:
        weeks = int(match.group(1))
        target_date = today - timedelta(weeks=weeks)
        return target_date.strftime('%y.%m.%d')

    # "어제"
    if '어제' in date_text:
        target_date = today - timedelta(days=1)
        return target_date.strftime('%y.%m.%d')

    # "YYYY.MM.DD" 또는 "YYYY-MM-DD" 또는 "YYYY/MM/DD"
    match = re.search(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', date_text)
    if match:
        year = match.group(1)[-2:]  # 마지막 2자리만
        month = int(match.group(2))
        day = int(match.group(3))
        return f"{year}.{month:02d}.{day:02d}"

    # "YY.MM.DD"
    match = re.search(r'(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})', date_text)
    if match:
        year = match.group(1)
        month = int(match.group(2))
        day = int(match.group(3))
        return f"{year}.{month:02d}.{day:02d}"

    # "MM월 DD일" (올해로 가정)
    match = re.search(r'(\d{1,2})\s*월\s*(\d{1,2})\s*일', date_text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.strftime('%y')
        return f"{year}.{month:02d}.{day:02d}"

    return ""


def extract_articles_from_page(driver, seen_links):
    """현재 페이지에서 기사 제목, 링크, 날짜 추출"""
    articles = []

    try:
        time.sleep(2)

        # BeautifulSoup으로 파싱 (더 안정적인 날짜 추출을 위해)
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')

        # Google News 검색 결과에서 기사 추출
        # SoaBEf 클래스가 있는 div가 각 뉴스 아이템
        news_items = soup.find_all('div', class_='SoaBEf')

        for item in news_items:
            try:
                # 제목 추출
                title_elem = item.find('div', role='heading')
                if not title_elem:
                    title_elem = item.find('h3')
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                # 링크 추출
                link_elem = item.find('a', href=True)
                if not link_elem:
                    continue

                link = link_elem.get('href', '')
                if '/url?q=' in link:
                    link = link.split('/url?q=')[1].split('&')[0]

                if not link or not link.startswith('http'):
                    continue
                if 'google.com' in link or 'google.co.kr' in link:
                    continue
                if link in seen_links:
                    continue

                # 날짜 추출 (여러 위치에서 시도)
                article_date = ""

                # 1. 날짜가 포함된 span 찾기 (보통 출처 옆에 있음)
                date_candidates = item.find_all('span')
                for span in date_candidates:
                    span_text = span.get_text(strip=True)
                    # 날짜 패턴 확인
                    if any(keyword in span_text for keyword in ['전', '일', '시간', '분', '주', '어제']):
                        parsed = parse_relative_date(span_text)
                        if parsed:
                            article_date = parsed
                            break
                    # 날짜 형식 확인 (YYYY.MM.DD 등)
                    import re
                    if re.search(r'\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}', span_text):
                        parsed = parse_relative_date(span_text)
                        if parsed:
                            article_date = parsed
                            break

                # 2. OSMtCf 클래스 (출처/날짜 영역)에서 찾기
                if not article_date:
                    source_area = item.find('div', class_='OSMtCf')
                    if source_area:
                        source_text = source_area.get_text(strip=True)
                        parsed = parse_relative_date(source_text)
                        if parsed:
                            article_date = parsed

                seen_links.add(link)
                articles.append({
                    'title': title,
                    'link': link,
                    'article_date': article_date
                })

            except Exception:
                continue

        # SoaBEf로 못 찾았으면 다른 방법 시도
        if not articles:
            try:
                selectors = [
                    'div[data-ved] h3', 'div.g h3', 'div[role="heading"]',
                    'h3.r', 'h3 a', 'a h3', 'div[role="article"] h3',
                    'article h3',
                ]

                for selector in selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            for elem in elements:
                                try:
                                    title = elem.text.strip()
                                    if not title or len(title) < 5:
                                        continue

                                    link = None
                                    if elem.get_attribute('role') == 'heading':
                                        try:
                                            soa_beef_parent = elem.find_element(By.XPATH, './ancestor::div[contains(@class, "SoaBEf")]')
                                            link_elem = soa_beef_parent.find_element(By.TAG_NAME, 'a')
                                            link = link_elem.get_attribute('href')
                                        except:
                                            try:
                                                parent = elem.find_element(By.XPATH, './ancestor::a[1]')
                                                link = parent.get_attribute('href')
                                            except:
                                                pass
                                    else:
                                        try:
                                            parent = elem.find_element(By.XPATH, './ancestor::a[1]')
                                            link = parent.get_attribute('href')
                                        except:
                                            try:
                                                child = elem.find_element(By.TAG_NAME, 'a')
                                                link = child.get_attribute('href')
                                            except:
                                                pass

                                    if link and link not in seen_links:
                                        if '/url?q=' in link:
                                            link = link.split('/url?q=')[1].split('&')[0]

                                        if link and link.startswith('http'):
                                            if 'google.com' in link or 'google.co.kr' in link:
                                                continue
                                            seen_links.add(link)
                                            articles.append({
                                                'title': title,
                                                'link': link,
                                                'article_date': ''  # 날짜는 본문에서 추출 시도
                                            })
                                except Exception:
                                    continue

                            if articles:
                                break
                    except:
                        continue
            except Exception as e:
                print(f"Selenium 요소 찾기 오류: {e}")

        return articles
    except Exception as e:
        print(f"기사 추출 오류: {e}")
        return []


def extract_recent_articles(driver, max_articles=MAX_ARTICLES_PER_QUERY):
    """최신 기사만 추출 (페이지네이션 지원)"""
    all_articles = []
    seen_links = set()
    page = 1
    
    while page <= MAX_PAGES and len(all_articles) < max_articles:
        articles = extract_articles_from_page(driver, seen_links)
        all_articles.extend(articles)
        
        if len(all_articles) >= max_articles:
            break
        
        if page < MAX_PAGES:
            try:
                current_url = driver.current_url
                if 'start=' in current_url:
                    start = int(current_url.split('start=')[1].split('&')[0])
                    next_start = start + 10
                else:
                    next_start = 10
                
                query = current_url.split('q=')[1].split('&')[0] if 'q=' in current_url else ''
                next_url = f"https://www.google.com/search?q={query}&tbm=nws&tbs=qdr:w&start={next_start}"
                
                driver.get(next_url)
                time.sleep(2)
                
                if driver.current_url == current_url:
                    break
                page += 1
            except Exception:
                break
        else:
            break
    
    return all_articles[:max_articles]


def extract_date_from_article_page(soup):
    """기사 페이지에서 발행일 추출"""
    import re
    from datetime import datetime

    # 1. meta 태그에서 날짜 추출 시도
    meta_tags = [
        ('meta', {'property': 'article:published_time'}),
        ('meta', {'property': 'og:article:published_time'}),
        ('meta', {'name': 'article:published_time'}),
        ('meta', {'name': 'pubdate'}),
        ('meta', {'name': 'date'}),
        ('meta', {'property': 'og:regDate'}),
        ('meta', {'name': 'DC.date.issued'}),
    ]

    for tag, attrs in meta_tags:
        elem = soup.find(tag, attrs)
        if elem:
            content = elem.get('content', '')
            if content:
                # ISO 형식 (2024-01-15T10:30:00+09:00)
                match = re.search(r'(\d{4})-(\d{2})-(\d{2})', content)
                if match:
                    year = match.group(1)[-2:]
                    month = int(match.group(2))
                    day = int(match.group(3))
                    return f"{year}.{month:02d}.{day:02d}"

    # 2. time 태그에서 추출
    time_elem = soup.find('time')
    if time_elem:
        datetime_attr = time_elem.get('datetime', '')
        if datetime_attr:
            match = re.search(r'(\d{4})-(\d{2})-(\d{2})', datetime_attr)
            if match:
                year = match.group(1)[-2:]
                month = int(match.group(2))
                day = int(match.group(3))
                return f"{year}.{month:02d}.{day:02d}"

    # 3. 일반적인 날짜 클래스/ID에서 추출
    date_selectors = [
        '.date', '.article-date', '.news-date', '.publish-date',
        '.post-date', '.entry-date', '#article-date', '.article_date',
        '.view_date', '.news_date', '.report_date', '.art_date',
        '[class*="date"]', '[class*="time"]'
    ]

    for selector in date_selectors:
        try:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                # YYYY.MM.DD 또는 YYYY-MM-DD 또는 YYYY/MM/DD
                match = re.search(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', text)
                if match:
                    year = match.group(1)[-2:]
                    month = int(match.group(2))
                    day = int(match.group(3))
                    return f"{year}.{month:02d}.{day:02d}"
                # YY.MM.DD
                match = re.search(r'(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})', text)
                if match:
                    year = match.group(1)
                    month = int(match.group(2))
                    day = int(match.group(3))
                    return f"{year}.{month:02d}.{day:02d}"
        except:
            continue

    return ""


async def get_article_content_async(session, semaphore, url, existing_date=""):
    """기사 본문 및 날짜 추출 (비동기)"""
    async with semaphore:  # 동시 요청 수 제한
        try:
            await asyncio.sleep(0.3)  # 요청 사이 딜레이

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"content": "", "article_date": existing_date}

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                # 기사 날짜 추출 (기존 날짜가 없는 경우에만)
                article_date = existing_date
                if not article_date:
                    article_date = extract_date_from_article_page(soup)

                for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                    tag.decompose()

                selectors = [
                    'article p', 'div.article-body p', 'div.article-content p',
                    'div.post-content p', 'div.content p', 'div#articleBody p'
                ]

                for selector in selectors:
                    paragraphs = soup.select(selector)
                    if paragraphs:
                        content = '\n\n'.join(
                            [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
                        )
                        if len(content) > 200:
                            return {"content": content, "article_date": article_date}

                body = soup.find('body')
                if body:
                    paragraphs = body.find_all('p')
                    if paragraphs:
                        content = '\n\n'.join(
                            [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
                        )
                        if len(content) > 200:
                            return {"content": content, "article_date": article_date}

                return {"content": "", "article_date": article_date}
        except asyncio.TimeoutError:
            print(f"    [타임아웃] {url[:50]}...")
            return {"content": "", "article_date": existing_date}
        except Exception as e:
            print(f"    [오류] {url[:50]}...: {e}")
            return {"content": "", "article_date": existing_date}


def get_column_letter(col_num):
    """컬럼 번호를 A1 표기법의 열 문자로 변환 (1-based)"""
    result = ""
    while col_num > 0:
        col_num -= 1
        result = chr(65 + (col_num % 26)) + result
        col_num //= 26
    return result


def ensure_correct_headers(worksheet):
    """시트 헤더가 올바른 순서인지 확인하고 필요시 업데이트

    올바른 순서: 경쟁사, 경쟁사+키워드, 제목, 본문, URL, 기사 날짜, 수집날짜, status
    """
    EXPECTED_HEADERS = ['경쟁사', '경쟁사+키워드', '제목', '본문', 'URL', '기사 날짜', '수집날짜', 'status']

    try:
        headers = worksheet.row_values(1)

        # 헤더가 없으면 새로 생성
        if not headers:
            worksheet.update('A1:H1', [EXPECTED_HEADERS])
            return EXPECTED_HEADERS

        # 헤더가 이미 올바른 순서인지 확인
        if headers == EXPECTED_HEADERS:
            return headers

        # 헤더가 다르면 필요한 컬럼만 추가 (기존 데이터 유지)
        # 누락된 컬럼 확인
        missing_cols = []
        for col in EXPECTED_HEADERS:
            if col not in headers:
                missing_cols.append(col)

        # 누락된 컬럼 추가 (맨 끝에)
        if missing_cols:
            for col in missing_cols:
                col_idx = len(headers)
                col_letter = get_column_letter(col_idx + 1)
                worksheet.update(f'{col_letter}1', [[col]])
                headers.append(col)
                print(f"  컬럼 '{col}' 추가됨 (위치: {col_letter})")

        return headers

    except Exception as e:
        print(f"헤더 확인 오류: {e}")
        return EXPECTED_HEADERS


def get_existing_urls(worksheet):
    """구글 시트에서 기존 URL 목록 가져오기 (URL 컬럼 기준)"""
    existing_urls = set()
    try:
        existing_data = worksheet.get_all_values()
        if len(existing_data) <= 1:
            return existing_urls
        
        headers = existing_data[0]
        # URL 컬럼 인덱스 찾기
        url_col_idx = None
        for idx, header in enumerate(headers):
            if header == 'URL':
                url_col_idx = idx
                break
        
        if url_col_idx is None:
            return existing_urls
        
        # URL 컬럼에서 값 가져오기
        for row in existing_data[1:]:
            if len(row) > url_col_idx:
                url = row[url_col_idx].strip()
                if url:  # 빈 문자열이 아닌 경우만 추가
                    existing_urls.add(url)
    except Exception:
        pass
    return existing_urls


async def crawl_articles_content_async(articles, existing_urls):
    """기사 본문들을 비동기로 크롤링"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    # 중복 제거 및 필터링
    new_articles = []
    for article in articles:
        if article['link'] not in existing_urls:
            new_articles.append(article)

    if not new_articles:
        return []

    print(f"  {len(new_articles)}개 신규 기사 본문 크롤링 시작 (비동기 처리)...")

    async with aiohttp.ClientSession() as session:
        # 모든 작업을 동시에 실행하기 위한 태스크 생성
        tasks = []
        article_list = []
        for article in new_articles:
            # 구글 검색에서 추출한 날짜를 전달
            existing_date = article.get('article_date', '')
            task = get_article_content_async(session, semaphore, article['link'], existing_date)
            tasks.append(task)
            article_list.append(article)

        # 모든 작업을 동시에 실행 (Semaphore로 동시 요청 수 제한됨)
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 정리
        results = []
        for i, (article, result) in enumerate(zip(article_list, results_raw), 1):
            if isinstance(result, Exception):
                print(f"  [{i}/{len(tasks)}] 오류: {article['title'][:50]}...: {result}")
                continue

            content = result.get('content', '') if isinstance(result, dict) else ''
            article_date = result.get('article_date', '') if isinstance(result, dict) else ''

            if content:
                results.append({
                    'title': article['title'],
                    'link': article['link'],
                    'content': content,
                    'article_date': article_date
                })
                print(f"  [{i}/{len(tasks)}] 완료: {article['title'][:50]}...")
            else:
                print(f"  [{i}/{len(tasks)}] 본문 추출 실패: {article['title'][:50]}...")

    return results


async def crawl_recent_news_async(
    spreadsheet_id,
    credentials_file='credentials.json',
    sheet_name=None
):
    """최신 기사만 크롤링하여 구글 시트에 추가 (비동기 버전)"""
    if not SHEETS_AVAILABLE:
        print("오류: gspread가 설치되지 않았습니다.")
        return False
    
    if not os.path.exists(credentials_file):
        print(f"오류: {credentials_file} 파일이 없습니다.")
        return False
    
    # 시트 이름이 지정되지 않으면 기본값 사용
    if sheet_name is None:
        sheet_name = GOOGLE_SHEET_NAME
    
    try:
        creds = Credentials.from_service_account_file(
            credentials_file,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except Exception:
            worksheet = spreadsheet.add_worksheet(
                title=sheet_name, rows=1000, cols=10
            )

        # 헤더 확인 및 업데이트 (올바른 순서로)
        headers = ensure_correct_headers(worksheet)
        
        print(f"구글 시트 연결 완료: {spreadsheet.url}")
    except Exception as e:
        print(f"구글 시트 연결 오류: {e}")
        return False
    
    existing_urls = get_existing_urls(worksheet)
    print(f"기존 기사 {len(existing_urls)}개 확인됨")
    
    driver = setup_driver()
    if not driver:
        return False
    
    all_search_queries = [f"{c} {k}" for c in COMPETITORS for k in KEYWORDS]
    new_articles_count = 0
    
    try:
        for idx, query in enumerate(all_search_queries, 1):
            print(f"\n[{idx}/{len(all_search_queries)}] {query} 처리 중...")
            
            if not search_google_news_recent(driver, query):
                continue
            
            articles = extract_recent_articles(driver, MAX_ARTICLES_PER_QUERY)
            print(f"  {len(articles)}개 기사 발견")
            
            if not articles:
                continue
            
            # 기사 본문을 비동기로 크롤링
            article_contents = await crawl_articles_content_async(articles, existing_urls)
            
            # 결과를 시트에 저장
            parts = query.split()
            competitor = parts[0] if parts else ''

            # 수집날짜 (YY.MM.DD 형식)
            from datetime import datetime
            crawl_date = datetime.now().strftime('%y.%m.%d')

            # 시트 헤더 다시 확인 (컬럼이 추가되었을 수 있음)
            headers = worksheet.row_values(1)

            for article_data in article_contents:
                url = article_data['link']
                if url in existing_urls:
                    continue

                existing_urls.add(url)

                try:
                    content_clean = article_data['content'].replace('\n', ' ').replace('\r', ' ')[:50000]
                    article_date = article_data.get('article_date', '')

                    # 헤더 구조에 맞게 데이터 구성
                    row_data = [''] * len(headers)

                    # 기본 컬럼 매핑
                    col_mapping = {
                        '경쟁사': competitor,
                        '경쟁사+키워드': query,
                        '제목': article_data['title'][:50000],
                        '본문': content_clean,
                        'URL': url,
                        '기사 날짜': article_date,
                        '수집날짜': crawl_date
                    }

                    # 각 컬럼에 데이터 할당
                    for idx, header in enumerate(headers):
                        if header in col_mapping:
                            row_data[idx] = col_mapping[header]

                    worksheet.append_row(row_data)
                    new_articles_count += 1
                    print(f"  ✓ 시트에 저장: {article_data['title'][:50]}... (날짜: {article_date or 'N/A'})")
                except Exception as e:
                    print(f"  시트 저장 오류: {e}")
            
            time.sleep(1)  # 쿼리 사이 딜레이
        
        print(f"\n완료: 신규 기사 {new_articles_count}개 추가됨")
        return True
        
    finally:
        driver.quit()


def crawl_recent_news(
    spreadsheet_id,
    credentials_file='credentials.json',
    sheet_name=None
):
    """동기 래퍼 함수"""
    if sheet_name is None:
        sheet_name = GOOGLE_SHEET_NAME
    return asyncio.run(crawl_recent_news_async(spreadsheet_id, credentials_file, sheet_name))


def main():
    """메인 실행 함수"""
    spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', '1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8')
    credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
    
    if not spreadsheet_id:
        print("오류: GOOGLE_SPREADSHEET_ID를 .env 파일에 설정해주세요.")
        return
    
    crawl_recent_news(spreadsheet_id, credentials_file, GOOGLE_SHEET_NAME)


if __name__ == "__main__":
    main()

