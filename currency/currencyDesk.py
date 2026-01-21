import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import yfinance as yf
from google import genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import json
from config import GEMINI_MODEL_NAME

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MODEL_NAME = GEMINI_MODEL_NAME

client = genai.Client(api_key=GOOGLE_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 환율 티커 정의 (Yahoo Finance 기준)
CURRENCY_TICKERS = {
    "USD/KRW": "USDKRW=X"
}

def get_currency_data():
    print("Fetching Currency Data...")
    data = {}
    
    for name, ticker in CURRENCY_TICKERS.items():
        try:
            # 최근 14일치 데이터를 가져와서 전일 대비 변화 및 트렌드 데이터 생성
            history = yf.Ticker(ticker).history(period="14d")
            if not history.empty:
                current_price = history['Close'].iloc[-1]
                prev_price = history['Close'].iloc[-2]
                change = ((current_price - prev_price) / prev_price) * 100
                
                # 그래프용 히스토리 데이터 (날짜, 종가)
                history_list = [
                    {
                        "date": date.strftime("%m.%d"),
                        "value": round(float(price), 2)
                    }
                    for date, price in zip(history.index, history['Close'])
                ]
                
                data[name] = {
                    "price": round(current_price, 2),
                    "change": round(change, 2),
                    "prev_close": round(prev_price, 2),
                    "history": history_list
                }
        except Exception as e:
            print(f"Error fetching {name}: {e}")
            
    return data

def analyze_currency(currency_data):
    print("AI Analyzing USD Market...")
    
    usd_info = currency_data.get("USD/KRW", {})
    current_price = usd_info.get("price")
    change = usd_info.get("change")
    
    prompt = f"""
    당신은 전문 외환 딜러이자 경제 분석가입니다. 
    제공된 원/달러(USD/KRW) 환율 데이터를 바탕으로 현시점의 시장 흐름을 분석하고 중계해주세요.
    
    [필독: 절대 준수 사항]
    1. 도입부 금지: '환율 분석입니다', '안녕하세요' 등 인삿말이나 서론 없이 바로 첫 번째 이모지와 본론으로 시작하세요.
    2. 특수문자 사용 금지: ** (볼드체), ! (느낌표), ~ (물결표) 등 모든 강조용 특수문자를 절대 사용하지 마세요. 오직 마침표(.)만 사용하세요.
    3. 수치 언급 금지: '1,320.5원'과 같은 구체적인 현재가 수치나 소수점 변동률(예: 0.25%)을 절대 직접 언급하지 마세요. 흐름(강세, 보합 등)으로만 설명하세요.

    [분석용 시장 데이터]
    - 데이터 요약: {json.dumps(usd_info, ensure_ascii=False)}

    작성 형식:
    - 내용을 3~4개의 짧은 포인트로 구성하세요.
    - 각 포인트 시작에는 하나의 이모지만 사용하고, 문단 사이에는 줄바꿈을 두 번 넣어주세요.
    - 총 5문장 내외로 명확하게 작성하며, 친절한 구어체(~해요, ~입니다)를 사용하세요.
    - 결과물에 텍스트와 이모지 외의 어떠한 마크다운 기호도 포함하지 마세요.
    - 원/달러 환율의 전반적인 방향성(상승/하락/횡보)과 그 배경이 되는 주요 경제적 요인을 짚어주세요.
    - 데이터에 기반한 현재 시장의 심리(공포, 낙관, 관망 등)를 설명하세요.
    - 현재 추세에서 유효한 환전 및 투자 대응 전략을 제안하세요.
    """
    
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )
    return response.text.strip()

def update_currency_desk():
    try:
        currency_data = get_currency_data()
        if not currency_data:
            print("No currency data fetched.")
            return

        analysis = analyze_currency(currency_data)
        
        # 주식시장 개장 상태 등을 고려한 제목 생성
        usd_price = currency_data.get("USD/KRW", {}).get("price", 0)
        display_price = int(usd_price) if isinstance(usd_price, (int, float)) else usd_price
        title = f"현재 환율 브리핑 (USD {display_price}원)"
        
        payload = {
            "id": 1,
            "currency_data": currency_data,
            "title": title,
            "analysis": analysis,
            "updated_at": datetime.now().isoformat()
        }
        
        # Supabase 업데이트
        result = supabase.table("currency_desk").upsert(payload).execute()
        print("Successfully updated Currency Desk!")
        
    except Exception as e:
        print(f"Update failed: {e}")


if __name__ == "__main__":
    update_currency_desk()
