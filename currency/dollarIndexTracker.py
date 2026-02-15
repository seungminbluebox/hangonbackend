import os
import sys
# 상위 디렉토리 참조 (로컬 config.py 우선권을 위해 sys.path 맨 앞에 추가)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import yfinance as yf
from google import genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import json
from config import GEMINI_MODEL_NAME
from news.push_notification import send_push_notification
from revalidate import revalidate_path

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MODEL_NAME = GEMINI_MODEL_NAME

client = genai.Client(api_key=GOOGLE_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 달러 인덱스 티커 정의 (Yahoo Finance 기준)
DXY_TICKER = "DX-Y.NYB"

def get_dxy_data():
    print("Fetching Dollar Index Data...")
    try:
        # 최근 10일치 데이터를 가져와서 전일 대비 변화 및 트렌드 데이터 생성
        history = yf.Ticker(DXY_TICKER).history(period="10d")
        if not history.empty:
            current_price = history['Close'].iloc[-1]
            prev_price = history['Close'].iloc[-2]
            change = current_price - prev_price
            change_percent = (change / prev_price) * 100
            
            # 그래프 분석용 히스토리 데이터 (최근 5일)
            recent_history = history.tail(5)
            history_list = [
                {
                    "date": date.strftime("%m.%d"),
                    "value": round(float(price), 2)
                }
                for date, price in zip(recent_history.index, recent_history['Close'])
            ]
            
            return {
                "price": round(current_price, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 2),
                "history": history_list
            }
    except Exception as e:
        print(f"Error fetching DXY: {e}")
            
    return None

def analyze_dxy(dxy_data):
    print("AI Analyzing Dollar Index (DXY)...")
    
    current_price = dxy_data.get("price")
    change_percent = dxy_data.get("change_percent")
    history_str = json.dumps(dxy_data.get("history"), ensure_ascii=False)
    
    prompt = f"""
    당신은 글로벌 매크로 경제 분석가입니다. 
    제공된 주요국 통화 대비 달러 가치를 나타내는 '달러 인덱스(DXY)' 데이터를 바탕으로 현시점의 시장 흐름을 분석하고 중계해주세요.
    
    [필독: 절대 준수 사항]
    1. 도입부 금지: '달러 인덱스 분석입니다', '안녕하세요' 등 인삿말이나 서론 없이 바로 첫 번째 이모지와 본론으로 시작하세요.
    2. 특수문자 사용 금지: ** (볼드체), ! (느낌표), ~ (물결표) 등 모든 강조용 특수문자를 절대 사용하지 마세요. 오직 마침표(.)만 사용하세요.
    3. 수치 언급 금지: '104.5'와 같은 구체적인 현재 지수나 소수점 변동률(예: 0.25%)을 절대 직접 언급하지 마세요. 흐름(강세, 약세, 보합 등)으로만 설명하세요.

    [분석용 시장 데이터]
    - 최근 5일 추이: {history_str}
    - 현재 변동 상황: {change_percent}% (양수면 상승, 음수면 하락)

    작성 형식:
    - 내용을 3~4개의 짧은 포인트로 구성하세요.
    - 각 포인트 시작에는 하나의 이모지만 사용하고, 문단 사이에는 줄바꿈을 두 번 넣어주세요.
    - 총 5문장 내외로 명확하게 작성하며, 친절한 구어체(~해요, ~입니다)를 사용하세요.
    - 결과물에 텍스트와 이모지 외의 어떠한 마크다운 기호도 포함하지 마세요.
    - 달러화의 강세 또는 약세 배경(미국 국채 금리, 통화 정책, 지정학적 리스크 등)을 짚어주세요.
    - 현재 추세가 국내 증시나 환율에 미칠 영향에 대해서도 짧게 언급하세요.
    """
    
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )
    return response.text.strip()

def update_dollar_index():
    try:
        dxy_data = get_dxy_data()
        if not dxy_data:
            print("No DXY data fetched.")
            return

        analysis = analyze_dxy(dxy_data)
        
        # 제목 생성 (지수를 정수로 표시)
        display_price = int(dxy_data.get("price", 0))
        title = f"달러 인덱스 브리핑 (DXY {display_price})"
        
        payload = {
            "id": 1,
            "title": title,
            "analysis": analysis,
            "updated_at": datetime.now().isoformat()
        }
        
        # Supabase 업데이트 (테이블명: dollar_index)
        # 테이블이 없으면 에러가 발생하므로, 사용자에게 테이블 생성을 안내해야 함
        try:
            result = supabase.table("dollar_index").upsert(payload).execute()
            print("Successfully updated Dollar Index!")
            revalidate_path("/dollar-index")
            
            # 푸시 알림 전송 (카테고리: us_dollar_index)
            send_push_notification(
                title=f"💵 {title}",
                body="달러 가치의 변화와 글로벌 시장 영향에 대한 리포트가 도착했습니다.",
                url="/dollar-index",
                category="us_dollar_index"
            )
        except Exception as e:
            print(f"Supabase or Push error: {e}")
            
    except Exception as e:
        print(f"Update failed: {e}")


if __name__ == "__main__":
    update_dollar_index()
