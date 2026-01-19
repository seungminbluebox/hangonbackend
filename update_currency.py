import os
import yfinance as yf
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import json

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 환율 티커 정의 (Yahoo Finance 기준)
CURRENCY_TICKERS = {
    "USD/KRW": "USDKRW=X",
    "JPY/KRW": "JPYKRW=X",
    "EUR/KRW": "EURKRW=X",
    "CNY/KRW": "CNYKRW=X"
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
    print("AI Analyzing Currency Market...")
    
    prompt = f"""
    당신은 전문 외환 딜러이자 경제 분석가입니다. 아래의 최신 환율 데이터를 분석하여 현재 외환 시장 상황을 중계해주세요.
    
    데이터: {json.dumps(currency_data, ensure_ascii=False)}
    
    작성 가이드:
    1. 내용을 3~4개의 짧은 포인트로 나누어 작성하세요.
    2. 각 포인트 시작에는 적절한 이모지(📍, 💵, 🌏, 💡 등)를 사용하고 줄바꿈을 두 번 넣어 가독성을 높이세요.
    3. 현재 원화의 흐름, 주요 통화(달러/엔) 특이점, 그리고 구체적인 환전 추천 전략을 포함하세요.
    4. 분석 문장은 총 5문장 이내로 아주 명확하고 핵심만 전달하세요.
    5. 어투는 친절한 구어체(~해요, ~입니다)를 사용하세요.
    """
    
    response = model.generate_content(prompt)
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
        print("\n[알림] 'currency_desk' 테이블이 없는 경우 Supabase SQL Editor에서 다음 명령어를 실행해주세요:")
        print("""
        CREATE TABLE currency_desk (
            id BIGINT PRIMARY KEY,
            currency_data JSONB,
            title TEXT,
            analysis TEXT,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """)

if __name__ == "__main__":
    update_currency_desk()
