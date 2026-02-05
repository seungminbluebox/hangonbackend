import os
import sys
# 상위 디렉토리 참조 (로컬 config.py 우선권을 위해 sys.path 맨 앞에 추가)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
import requests
import feedparser
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime
from google import genai
from supabase import create_client, Client
from dotenv import load_dotenv
from newspaper import Article, Config
from config import GEMINI_MODEL_NAME
from news.push_notification import send_push_to_all
import base64

load_dotenv()
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)
MODEL_NAME = GEMINI_MODEL_NAME
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TTS_KEY=os.getenv("GOOGLE_TTS_API_KEY")
# --- [모듈 4] TTS 생성 (Google Cloud TTS) ---

def generate_tts_content(text):
    print("Generating TTS content with Google Cloud TTS...")
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={TTS_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": "ko-KR",
            "name": "ko-KR-Chirp3-HD-Despina"
        },
        "audioConfig": {
            "audioEncoding": "MP3"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json().get("audioContent")
        else:
            print(f"TTS API Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error generating TTS: {e}")
        return None

# --- [모듈 3] 보고서 생성 (Gemini) ---

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
        for article in articles[:50]:
            title_tag = article.select_one("dd.articleSubject a") or article.select_one("dt.articleSubject a")
            summary_tag = article.select_one("dd.articleSummary")
            if title_tag and summary_tag:
                news_items.append({
                    "title": title_tag.text.strip(),
                    "snippet": summary_tag.text.strip().replace("\n", " ")[:200],
                    "source": "Naver Finance"
                })
        return news_items
    except Exception as e:
        print(f"Error fetching Naver: {e}")
        return []

def fetch_yahoo_finance_rss():
    print("Fetching Yahoo Finance RSS...")
    rss_url = "https://finance.yahoo.com/news/rss/topstories"
    try:
        feed = feedparser.parse(rss_url)
        news_items = []
        for entry in feed.entries[:30]:
            news_items.append({
                "title": entry.title,
                "summary": entry.get('summary', '')[:200],
                "source": "Yahoo Finance"
            })
        return news_items
    except Exception as e:
        print(f"RSS Load Error: {e}")
        return []

# --- [모듈 2] 시장 데이터 수집 (Market Data) ---

def fetch_market_summary():
    print("Fetching Market Summary Data...")
    symbols = {
        "S&P 500": "^GSPC",
        "Nasdaq": "^IXIC",
        "Dow Jones": "^DJI",
        "KOSPI": "^KS11",
        "KOSDAQ": "^KQ11",
        "USD/KRW": "USDKRW=X",
        "Gold": "GC=F",
        "WTI Crude Oil": "CL=F",
        "10Y Treasury": "^TNX"
    }
    
    market_status = {}
    for name, symbol in symbols.items():
        try:
            ticker = yf.Ticker(symbol)
            # 1일 데이터 가져오기
            history = ticker.history(period="2d")
            if len(history) >= 2:
                current_price = history['Close'].iloc[-1]
                prev_price = history['Close'].iloc[-2]
                change = current_price - prev_price
                percent_change = (change / prev_price) * 100
                market_status[name] = {
                    "price": round(current_price, 2),
                    "change": round(change, 2),
                    "percent": round(percent_change, 2)
                }
        except Exception as e:
            print(f"Error fetching {name}: {e}")
    return market_status

# --- [모듈 3] 보고서 생성 (Gemini) ---

def generate_daily_report(news_data, market_data):
    print("Generating Daily Report with Gemini...")
    
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    
    prompt = f"""
    너는 세계 최고의 경제 분석가이자 시장 전략가야. 
    아래 제공된 [시장 지표]와 [최신 뉴스 정보]를 바탕으로, 투자자들이 하루를 시작하거나 마무리할 때 꼭 읽어야 할 '데일리 거시경제 리포트'를 작성해줘.

    [시장 지표]
    {json.dumps(market_data, ensure_ascii=False, indent=2)}

    [최신 뉴스]
    {json.dumps(news_data, ensure_ascii=False, indent=2)}

    [시스템 관련 링크 정보]
    보고서 내용 중 아래 주제와 연관된 내용이 나오면, 해당 문단 바로 위나 문장 끝에 자연스럽게 마크다운 링크([이름](경로))를 삽입하여 사용자의 클릭을 유도해줘.
    - 국내 공포 탐욕 지수: [/kospi-fear-greed](/kospi-fear-greed)
    - 미국 공포 탐욕 지수: [/fear-greed](/fear-greed)
    - 국내 자금 흐름: [/money-flow/domestic](/money-flow/domestic)
    - 미국 자금 흐름: [/money-flow/us](/money-flow/us)
    - 코스피 선물 지표: [/kospi-futures](/kospi-futures)
    - 나스닥 선물 지표: [/nasdaq-futures](/nasdaq-futures)
    - 신용융자 잔고(빚투 현황): [/credit-balance](/credit-balance)
    - 환율 분석 데스크: [/currency-desk](/currency-desk)
    - 금리 정보: [/interest-rate](/interest-rate)
    - 안전자산 vs 위험자산 심리: [/money-flow/safe](/money-flow/safe)
    - 풋/콜 옵션 비율: [/put-call-ratio](/put-call-ratio)

    [작성 가이드라인]
    1. 제목: 오늘의 시장을 가장 잘 나타내는 강렬하고 전문적인 제목 (예: "{today_str} 글로벌 마켓 데일리 브리핑: 'K-증시의 전성시대'와 달러 약세의 서막")
    2. 핵심 요약: 오늘의 시장을 관통하는 핵심 테마를 2~3문장으로 깊이 있게 정리.
    3. 주요 증시 및 지표 분석: 나스닥, S&P 500, 코스피 등 주요 지수의 움직임을 '왜(Why)' 움직였는지 거시경제적 맥락으로 설명. (섹션별로 구분)
    4. 섹터 및 개별 이슈: 시장에 큰 영향을 미친 특정 기업 실적, 정책, 지정학적 이슈 분석.
    5. 향후 관전 포인트: 투자자가 내일 주목해야 할 핵심 변수들을 리스트업.
    6.內部 링크 활용: 문맥상 적절한 곳에 [시스템 관련 링크 정보]를 적극적으로 활용하여 사용자가 상세 지표를 바로 확인할 수 있게 해줘. (예: "투자 심리가 극도로 위축되며 [공포 탐욕 지수](/fear-greed)가 위험 수준에 도달했습니다.")
    7. 금지 사항: 
       - 문단 사이나 섹션 구분을 위해 '---' 나 '===' 같은 특수기호 구분선을 사용하지 마세요. (마운다운 헤더 #, ## 사용으로 충분함)
       - 불필요한 서술은 제외하고 간결하고 명확한 문체로 작성하세요.
    8. 톤앤매너: 신뢰감을 주는 전문적인 어조(해요체 또는 하십시오체보단 권장합니다, 중립적인 표현 사용)로 작성하되, 딱딱하지 않게 자연스러운 흐름 유지.
    9. 형식: 정교한 Markdown 형식 사용 금지, 오직 텍스트 기반으로 작성.

    최종 출력은 오직 JSON 형식으로만 해줘.
    {{
        "date": "{datetime.now().strftime("%Y-%m-%d")}",
        "title": "...",
        "content": " 여기에 전체 마크다운 리포트 내용 삽입 (구분선 특수문자 금지) 날짜는 여기에 포함하지 말것 ",
        "summary": " 한 줄 요약 (리포트 상단에 강조될 내용) ",
        "audio_script": " 년/월/일/요일 에 대한 리포트라는 내용이 처음에 나올 것. 전문 경제 앵커가 리포트를 부드럽게 낭독해주는 듯한 구어체 기반의 방송 대본. (중요: 숫자는 읽을 때 어색하지 않도록 1,445포인트는 '천사백사십오 포인트'와 같이 가급적 한글로 풀어서 작성하거나 단위를 반드시 포함할 것, 마크다운 없이 텍스트로만 작성, '안녕하세요', '전해드립니다' 등의 자연스러운 연결어 포함) "
    }}
    """
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error in report generation: {e}")
        return None

def save_to_supabase(report_data):
    if not report_data:
        return
    print("Saving report to Supabase...")
    try:
        # daily_reports 테이블에 업서트 (날짜 기준)
        # 테이블이 없는 경우를 대비해 에러 핸들링
        result = supabase.table("daily_reports").upsert(report_data, on_conflict="date").execute()
        print("Report successfully saved!")
        return result
    except Exception as e:
        print(f"Error saving to Supabase: {e}")
        print("Creating table might be needed: CREATE TABLE daily_reports (id bigint primary key generated always as identity, date date unique, title text, content text, summary text, audio_script text, audio_content text, created_at timestamptz default now());")

def main():
    news_kr = fetch_naver_finance_main()
    news_us = fetch_yahoo_finance_rss()
    market = fetch_market_summary()
    
    report = generate_daily_report(news_kr + news_us, market)
    
    if report:
        # TTS 생성 및 추가
        if report.get("audio_script"):
            audio_content = generate_tts_content(report["audio_script"])
            if audio_content:
                report["audio_content"] = audio_content
                print("Audio content successfully generated and added to report.")
        
        save_to_supabase(report)
        # 푸시 알림 전송
        print("Sending push notifications...")
        try:
            now = datetime.now()
            date_str = f"{now.month}월 {now.day}일"
            send_push_to_all(
                title="Hang on!",
                body=f"{date_str} 새로운 경제 리포트가 업데이트되었습니다.",
                url="/news/daily-report"
            )
        except Exception as e:
            print(f"Error sending push: {e}")
    else:
        print("Failed to generate report.")

if __name__ == "__main__":
    main()
