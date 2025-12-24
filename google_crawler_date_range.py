#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구글 뉴스 크롤러 - 날짜 범위 지정 버전
시작일과 종료일을 지정하여 특정 기간의 기사만 크롤링하여 구글 시트에 추가
"""

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
from datetime import datetime
from urllib.parse import quote

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
    "뷰핏", "레드밸런스", "SNPE", "헬스맥스"
]

KEYWORDS = ["도입", "협약", "협업", "제휴"]

MAX_ARTICLES_PER_QUERY = 20
MAX_PAGES = 2

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


def format_date_for_google(date_str):
    """
    날짜 문자열을 구글 검색용 형식(MM/DD/YYYY)으로 변환
    
    Args:
        date_str: 날짜 문자열 (YYYY-MM-DD, YYYY/MM/DD, YY.MM.DD 등)
    
    Returns:
        str: MM/DD/YYYY 형식의 날짜 문자열
    """
    try:
        # 다양한 입력 형식 지원
        date_str = date_str.strip().replace('.', '-').replace('/', '-')
        
        # YYYY-MM-DD 형식으로 변환 시도
        if len(date_str.split('-')) == 3:
            parts = date_str.split('-')
            if len(parts[0]) == 4:  # YYYY-MM-DD
                year, month, day = parts
            elif len(parts[2]) == 4:  # DD-MM-YYYY
                day, month, year = parts
            else:  # YY-MM-DD (2자리 연도)
                year, month, day = parts
                year = '20' + year if int(year) < 50 else '19' + year
        else:
            raise ValueError("날짜 형식을 인식할 수 없습니다.")
        
        # MM/DD/YYYY 형식으로 변환
        return f"{int(month):02d}/{int(day):02d}/{year}"
    except Exception as e:
        raise ValueError(f"날짜 변환 오류: {e}. 올바른 형식 예: '2024-01-01', '2024/01/01', '24.01.01'")


def search_google_news_date_range(driver, query, start_date, end_date):
    """
    구글 뉴스 검색 (날짜 범위 지정)
    
    Args:
        driver: Selenium WebDriver 객체
        query: 검색어
        start_date: 시작일 (MM/DD/YYYY 형식 또는 변환 가능한 형식)
        end_date: 종료일 (MM/DD/YYYY 형식 또는 변환 가능한 형식)
    
    Returns:
        bool: 성공 여부
    """
    try:
        # 날짜 형식 변환
        start_formatted = format_date_for_google(start_date)
        end_formatted = format_date_for_google(end_date)
        
        # 구글 검색 URL 생성 (날짜 범위 지정)
        # tbs=cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY
        date_range = f"cdr:1,cd_min:{start_formatted},cd_max:{end_formatted}"
        url = f"https://www.google.com/search?q={quote(query)}&tbm=nws&tbs={date_range}"
        
        print(f"  검색 URL: {url[:100]}...")
        driver.get(url)
        time.sleep(3)
        return True
    except Exception as e:
        print(f"  날짜 범위 검색 오류: {e}")
        return False


def extract_articles_from_page(driver, seen_links):
    """현재 페이지에서 기사 제목과 링크 추출"""
    articles = []
    
    try:
        time.sleep(2)
        
        try:
            selectors = [
                'div[data-ved] h3', 'div.g h3', 'div[role="heading"]',
                'h3.r', 'h3 a', 'a h3', 'div[role="article"] h3',
                'article h3', 'div.SoaBEf div[role="heading"]', 'div.SoaBEf a',
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
                                        articles.append({'title': title, 'link': link})
                            except Exception:
                                continue
                        
                        if articles:
                            break
                except:
                    continue
        except Exception as e:
            print(f"Selenium 요소 찾기 오류: {e}")
        
        if not articles:
            try:
                page_source = driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                
                selectors = [
                    ('div', {'class': 'SoaBEf'}), ('div', {'class': 'g'}),
                    ('div', {'data-ved': True}), ('div', {'role': 'article'}),
                ]
                
                for tag, attrs in selectors:
                    results = soup.find_all(tag, attrs) if attrs else soup.find_all(tag)
                    if results:
                        for result in results:
                            try:
                                title_elem = result.find('h3') or result.find('div', role='heading')
                                if title_elem:
                                    title = title_elem.get_text(strip=True)
                                    link_elem = title_elem.find('a')
                                    if not link_elem:
                                        link_elem = result.find('a', href=True)
                                    
                                    if link_elem:
                                        link = link_elem.get('href', '')
                                        if '/url?q=' in link:
                                            link = link.split('/url?q=')[1].split('&')[0]
                                        
                                        if link and link.startswith('http'):
                                            if 'google.com' in link or 'google.co.kr' in link:
                                                continue
                                            if link not in seen_links and len(title) > 5:
                                                seen_links.add(link)
                                                articles.append({'title': title, 'link': link})
                            except:
                                continue
                        
                        if articles:
                            break
            except Exception as e:
                print(f"BeautifulSoup 파싱 오류: {e}")
        
        return articles
    except Exception as e:
        print(f"기사 추출 오류: {e}")
        return []


def extract_articles_with_pagination(driver, max_articles=MAX_ARTICLES_PER_QUERY, start_date=None, end_date=None):
    """기사 추출 (페이지네이션 지원, 날짜 범위 유지)"""
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
                
                # 날짜 범위 파라미터 유지
                query = current_url.split('q=')[1].split('&')[0] if 'q=' in current_url else ''
                
                if start_date and end_date:
                    start_formatted = format_date_for_google(start_date)
                    end_formatted = format_date_for_google(end_date)
                    date_range = f"cdr:1,cd_min:{start_formatted},cd_max:{end_formatted}"
                    next_url = f"https://www.google.com/search?q={query}&tbm=nws&tbs={date_range}&start={next_start}"
                else:
                    next_url = f"https://www.google.com/search?q={query}&tbm=nws&start={next_start}"
                
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


def get_article_content(driver, url):
    """기사 본문 추출"""
    try:
        driver.set_page_load_timeout(10)
        driver.get(url)
        time.sleep(1)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
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
                    return content
        
        body = soup.find('body')
        if body:
            paragraphs = body.find_all('p')
            if paragraphs:
                content = '\n\n'.join(
                    [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
                )
                if len(content) > 200:
                    return content
        
        return ""
    except Exception:
        return ""


def get_existing_urls(worksheet):
    """구글 시트에서 기존 URL 목록 가져오기 (마지막 컬럼 기준)"""
    existing_urls = set()
    try:
        existing_data = worksheet.get_all_values()
        if len(existing_data) > 1:
            for row in existing_data[1:]:
                if len(row) >= 1:
                    existing_urls.add(row[-1].strip())
    except Exception:
        pass
    return existing_urls


def crawl_news_by_date_range(
    start_date,
    end_date,
    spreadsheet_id=None,
    credentials_file='credentials.json',
    sheet_name='시트11'
):
    """
    지정된 날짜 범위의 기사만 크롤링하여 구글 시트에 추가
    
    Args:
        start_date: 시작일 (예: '2024-01-01', '2024/01/01', '24.01.01')
        end_date: 종료일 (예: '2024-12-31', '2024/12/31', '24.12.31')
        spreadsheet_id: 구글 스프레드시트 ID (None이면 .env에서 가져옴)
        credentials_file: 구글 인증 파일 경로
        sheet_name: 시트 이름
    """
    if not SHEETS_AVAILABLE:
        print("오류: gspread가 설치되지 않았습니다.")
        return False
    
    # 환경 변수에서 가져오기
    if spreadsheet_id is None:
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', '1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8')
        credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', credentials_file)
        sheet_name = os.getenv('GOOGLE_CRAWL_WORKSHEET', sheet_name)
    
    if not spreadsheet_id:
        print("오류: GOOGLE_SPREADSHEET_ID를 .env 파일에 설정해주세요.")
        return False
    
    if not os.path.exists(credentials_file):
        print(f"오류: {credentials_file} 파일이 없습니다.")
        return False
    
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
            worksheet.append_row(['경쟁사', '경쟁사+키워드', '제목', '본문', 'URL'])
        
        print(f"구글 시트 연결 완료: {spreadsheet.url}")
        print(f"크롤링 기간: {start_date} ~ {end_date}")
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
            
            if not search_google_news_date_range(driver, query, start_date, end_date):
                print(f"  검색 실패, 건너뜀")
                continue
            
            articles = extract_articles_with_pagination(driver, MAX_ARTICLES_PER_QUERY, start_date, end_date)
            print(f"  {len(articles)}개 기사 발견")
            
            for i, article in enumerate(articles, 1):
                url = article['link']
                
                if url in existing_urls:
                    print(f"  [{i}/{len(articles)}] 중복 기사 건너뜀: {article['title'][:50]}...")
                    continue
                
                existing_urls.add(url)
                print(f"  [{i}/{len(articles)}] {article['title'][:50]}...")
                
                content = get_article_content(driver, url)
                
                parts = query.split()
                competitor = parts[0] if parts else ''
                
                try:
                    content_clean = content.replace('\n', ' ').replace('\r', ' ')[:50000]
                    worksheet.append_row([
                        competitor,
                        query,
                        article['title'][:50000],
                        content_clean,
                        url
                    ])
                    new_articles_count += 1
                    print("  시트에 저장 완료")
                except Exception as e:
                    print(f"  시트 저장 오류: {e}")
                
                time.sleep(0.5)
            
            time.sleep(1)
        
        print(f"\n완료: 신규 기사 {new_articles_count}개 추가됨")
        print(f"크롤링 기간: {start_date} ~ {end_date}")
        return True
        
    finally:
        driver.quit()


def main():
    """메인 실행 함수"""
    import sys
    
    # 명령줄 인자로 날짜 지정
    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    else:
        # 사용 예시
        print("사용법: python google_crawler_date_range.py <시작일> <종료일>")
        print("예시: python google_crawler_date_range.py 2024-01-01 2024-01-31")
        print("예시: python google_crawler_date_range.py 2024/01/01 2024/01/31")
        print("\n날짜 형식: YYYY-MM-DD, YYYY/MM/DD, YY.MM.DD 등")
        print("\n인자 없이 실행하면 기본값 사용:")
        print("  시작일: 2024-01-01")
        print("  종료일: 오늘")
        
        # 기본값: 올해 1월 1일부터 오늘까지
        start_date = datetime.now().strftime('%Y-01-01')
        end_date = datetime.now().strftime('%Y-%m-%d')
        
        print(f"\n기본값으로 실행: {start_date} ~ {end_date}")
        response = input("계속하시겠습니까? (y/n): ")
        if response.lower() != 'y':
            return
    
    spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', '1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8')
    credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
    sheet_name = os.getenv('GOOGLE_CRAWL_WORKSHEET', '시트11')
    
    crawl_news_by_date_range(
        start_date=start_date,
        end_date=end_date,
        spreadsheet_id=spreadsheet_id,
        credentials_file=credentials_file,
        sheet_name=sheet_name
    )


if __name__ == "__main__":
    main()
