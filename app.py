import os
import json
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
from newspaper import Article, Config

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
genai.configure(api_key=GOOGLE_API_KEY)
MODEL_NAME = 'gemini-2.0-flash' 
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- [모듈 1] 데이터 수집 (Collector) ---

def fetch_naver_finance_main():
    print("Fetching Naver Finance Main News...")
    url = "https://finance.naver.com/news/mainnews.naver"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news_items = []
        articles = soup.select(".mainNewsList li")
        
        for article in articles[:100]:  # 상위 100개만
            # 제목 추출
            title_tag = article.select_one("dd.articleSubject a")
            if not title_tag: # 썸네일 구조일 경우 dt 태그일 수 있음
                title_tag = article.select_one("dt.articleSubject a")
            
            # 요약(Snippet) 추출
            summary_tag = article.select_one("dd.articleSummary")
            
            if title_tag and summary_tag:
                title = title_tag.text.strip()
                link = "https://finance.naver.com" + title_tag['href']
                snippet = summary_tag.text.strip().replace("\n", " ")[:150] # 앞 150자만
                
                news_items.append({
                    "title": title,
                    "snippet": snippet,
                    "url": link
                })
                
        return news_items
    except Exception as e:
        print(f"Error fetching Naver: {e}")
        return []

def fetch_yahoo_finance_stable():
    print("Fetching Yahoo Finance Top Stories with newspaper3k...")
    rss_url = "https://finance.yahoo.com/news/rss/topstories"
    
    # 봇 탐지 우회를 위한 설정
    user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36'
    config = Config()
    config.browser_user_agent = user_agent
    config.request_timeout = 10

    try:
        feed = feedparser.parse(rss_url)
        news_items = []
        
        # 속도 및 차단 방지를 위해 상위 30개만 테스트
        for entry in feed.entries[:25]: 
            try:
                # 1. URL 확보
                url = entry.link
                
                # 2. Article 객체 생성 및 다운로드 (newspaper3k가 알아서 처리)
                article = Article(url, config=config)
                article.download() # HTML 다운로드
                article.parse()    # 본문 추출 알고리즘 가동
                
                # 3. 데이터 정제 (nlp()를 호출하면 키워드/요약도 자동 추출 가능하지만 여기선 생략)
                full_text = article.text
                
                # 본문이 비어있으면 RSS의 summary로 대체
                if not full_text:
                     full_text = entry.get('summary', entry.get('description', ''))

                news_items.append({
                    "title": article.title if article.title else entry.title,
                    "content": full_text, # 전체 본문
                    "summary": full_text[:200] + "..." if len(full_text) > 200 else full_text,
                    "url": url
                })
                print(f"Success: {entry.title[:15]}...")
                
            except Exception as e:
                print(f"Failed to parse {entry.link}: {e}")
                # 실패 시 RSS 기본 정보만 저장
                news_items.append({
                    "title": entry.title,
                    "content": entry.get('summary', ''),
                    "url": entry.link
                })

        return news_items

    except Exception as e:
        print(f"RSS Load Error: {e}")
        return []

def process_news_with_gemini(raw_news_list):
    """수집된 뉴스 리스트를 Gemini에게 보내 중요 뉴스 5개 선별"""
    print("Processing with Gemini AI...")
    
    if not raw_news_list:
        print("No news to process.")
        return []

    model = genai.GenerativeModel(MODEL_NAME)
    
    prompt = f"""
    너는 전문 경제 애널리스트야. 아래 제공된 [뉴스 데이터]는 한국과 세계의 주요 경제 뉴스들이야.
    하루에 한번 5가지의 소식만 골라서 보여줘야 하니, 이 중에서 가장 '경제적 파급력(굵직한 소식)'이 크고 중요한 사건 5가지를 선별해줘. 

    [요구사항]
    1. 다양성: 한국(KR)/미국(US)/글로벌(Global) 이슈를 적절히 섞어서 총 5개를 맞춰줘. 
    2. 재가공:
       - `keyword`: 자극적이지 않고 사실에 기반한 명확한 헤드라인으로 새로 작성해.
       - `summary`: `- 요약 내용 1\\n- 요약 내용 2\\n- 시장 전망/시사점(~할 전망임이 아닌 그저 가능성이 있을수도있다는 식의 서술)` 
       - `links`: 선별된 뉴스의 원본 URL과 제목을 반드시 아래 예시와 같은 객체 배열 형식으로 포함해.
    3. 출력 형식: 반드시 아래 JSON 포맷(Array of Objects)으로만 출력해. Markdown 코드 블럭(```json)을 쓰지 마.
    4. 각 뉴스의 `keyword`에 마지막에 keyword에 맞는 이모지 사용(감정 이모지는 금지)
    5. summary 요약 작성시 최대한 단어로 문장을 끝맺음, 한 줄마다 50자 정도로 작성할 것.
    6. 기업에 대한 뉴스가 나올경우 category는 해당 기업의 소속 국가로 맞출것.
    7. 원자제, 암호화폐 뉴스의 category는 Global임.


    [선정 기준]
    0. 지수 신고가, 환율 변동, 금리 변동을 알리는 직접적인 뉴스인가?
    1. 뉴스가 시장에 미치는 영향력이 큰가?
    2. 전망, 예측보단 현재 상황을 명확히 설명하는 뉴스인가?
    3. 지수, 환율, 금리, 중요한 정책 위주의 뉴스인가?
    4. 국가 정책, 금리, 환율등 과 같은 주요 이슈인가?
    5. 글로벌 빅테크나 주요 산업의 판도를 바꿀 만한 사건인가?
    6. 누군가(어느집단, 단체)의 의견, 예측이 아닌 현재의 객관적 사실에 기반한 뉴스인가?
    7. 겹치는 주제는 중복 선정을 피하고 다양한 이슈를 선정하는가?
    
    [JSON 예시]
    [
      {{
        "category": "KR"(keyword, summary 내용에 맞게 분류) global은 미국이 아닌 나라의 뉴스임,
        "keyword": "삼성전자 어닝쇼크, 반도체 부진 심화", 
        "summary": "-삼성전자가 3분기 영업이익이 전년 대비 대폭 감소했다고 발표.\n-반도체 수요 둔화가 주요 원인.\n-글로벌 경기 침체 우려와 맞물려 IT 업계 전반에 부정적 영향을 미칠 여지가 존재.", 
        "links": [
          {{
            "url": "https://news.naver.com/...",
            "title": "삼성전자, 3분기 영업이익 2.4조원... 시장 예상치 하회"
          }}
        ]
      }}
    ]

    [뉴스 데이터]
    {json.dumps(raw_news_list, ensure_ascii=False)}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        response_text = response.text
        
        return json.loads(response_text, strict=False)
    except Exception as e:
        print(f"Error in Gemini processing: {e}")
        return []

def save_to_supabase(data):
    print(f"Saving {len(data)} items to Supabase...")
    if not data:
        print("No data to save.")
        return
    try:
        result = supabase.table("daily_news").insert(data).execute()
        print("Successfully saved!")
        return result
    except Exception as e:
        print(f"Error saving to Supabase: {e}")

def main():
    kr_news = fetch_naver_finance_main()
    us_news = fetch_yahoo_finance_stable()
    
    all_news = kr_news + us_news
    print(f"Total collected raw news: {len(all_news)} items")
    
    final_news = process_news_with_gemini(all_news)
    
    if final_news:
        print("Top 5 News Selected:")
        for idx, item in enumerate(final_news):
            print(f"{idx+1}. [{item['category']}] {item['keyword']}")
        save_to_supabase(final_news)
    else:
        print("Failed to generate news summary.")

if __name__ == "__main__":
    main()