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


async def get_article_content_async(session, semaphore, url):
    """기사 본문 추출 (비동기)"""
    async with semaphore:  # 동시 요청 수 제한
        try:
            await asyncio.sleep(0.3)  # 요청 사이 딜레이
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return ""
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
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
        except asyncio.TimeoutError:
            print(f"    [타임아웃] {url[:50]}...")
            return ""
        except Exception as e:
            print(f"    [오류] {url[:50]}...: {e}")
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
            task = get_article_content_async(session, semaphore, article['link'])
            tasks.append(task)
            article_list.append(article)
        
        # 모든 작업을 동시에 실행 (Semaphore로 동시 요청 수 제한됨)
        contents = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 결과 정리
        results = []
        for i, (article, content) in enumerate(zip(article_list, contents), 1):
            if isinstance(content, Exception):
                print(f"  [{i}/{len(tasks)}] 오류: {article['title'][:50]}...: {content}")
                continue
            if content:
                results.append({
                    'title': article['title'],
                    'link': article['link'],
                    'content': content
                })
                print(f"  [{i}/{len(tasks)}] 완료: {article['title'][:50]}...")
            else:
                print(f"  [{i}/{len(tasks)}] 본문 추출 실패: {article['title'][:50]}...")
    
    return results


async def crawl_recent_news_async(
    spreadsheet_id,
    credentials_file='credentials.json',
    sheet_name='시트7'
):
    """최신 기사만 크롤링하여 구글 시트에 추가 (비동기 버전)"""
    if not SHEETS_AVAILABLE:
        print("오류: gspread가 설치되지 않았습니다.")
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
            
            for article_data in article_contents:
                url = article_data['link']
                if url in existing_urls:
                    continue
                
                existing_urls.add(url)
                
                try:
                    content_clean = article_data['content'].replace('\n', ' ').replace('\r', ' ')[:50000]
                    worksheet.append_row([
                        competitor,
                        query,
                        article_data['title'][:50000],
                        content_clean,
                        url
                    ])
                    new_articles_count += 1
                    print(f"  ✓ 시트에 저장: {article_data['title'][:50]}...")
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
    sheet_name='경쟁사 동향 분석'
):
    """동기 래퍼 함수"""
    return asyncio.run(crawl_recent_news_async(spreadsheet_id, credentials_file, sheet_name))


def main():
    """메인 실행 함수"""
    spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', '1oYJqCNpGAPBwocvM_yjgXqLBUR07h9_GoiGcAFYQsF8')
    credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
    sheet_name = os.getenv('GOOGLE_CRAWL_WORKSHEET', '경쟁사 동향 분석')
    
    if not spreadsheet_id:
        print("오류: GOOGLE_SPREADSHEET_ID를 .env 파일에 설정해주세요.")
        return
    
    crawl_recent_news(spreadsheet_id, credentials_file, sheet_name)


if __name__ == "__main__":
    main()

