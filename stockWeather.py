import os
import json
import yfinance as yf
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") 
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(MODEL_NAME)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_market_indices():
    print("Fetching market indices...")
    symbols = {
        "KOSPI": "^KS11",
        "KOSDAQ": "^KQ11",
        "S&P 500": "^GSPC",
        "Nasdaq": "^IXIC",
        "10Y Yield": "^TNX",
        "Dollar Index": "DX-Y.NYB",
        "VIX": "^VIX",
        "Gold": "GC=F",
        "Oil": "CL=F"
    }
    
    results = {}
    for name, symbol in symbols.items():
        try:
            ticker = yf.Ticker(symbol)
            # 최신 2일간의 데이터를 가져와 증감 계산
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                current_price = hist['Close'].iloc[-1]
                prev_price = hist['Close'].iloc[-2]
                change = current_price - prev_price
                pct_change = (change / prev_price) * 100
                results[name] = {
                    "price": round(current_price, 2),
                    "change": round(pct_change, 2)
                }
            else:
                # 데이터가 부족할 경우 최신값 하나라도 가져옴
                results[name] = {"price": round(hist['Close'].iloc[-1], 2), "change": 0.0}
        except Exception as e:
            print(f"Error fetching {name}: {e}")
            
    return results

def analyze_weather(market_data):
    print("Analyzing market weather with AI...")
    
    prompt = f"""
    당신은 시장의 분위기를 '날씨'로 비유해서 알려주는 친절한 기상캐스터입니다.
    현재 글로벌 및 국내 주요 지표들을 보고 오늘의 '경제 기상도'를 작성해 주세요.
    특수문자 **같은 물결표는 사용 금지**입니다. 텍스트만 작성해 주세요.

    [시장 지표]
    {json.dumps(market_data, indent=2)}

    [날씨 기준 가이드]
    - 맑음 (Sunny): 지수들이 전반적으로 상승하고 변동성(VIX)이 낮아 평온한 상태.
    - 구름조금 (Partly Cloudy): 지수별로 희비가 엇갈리거나, 아주 완만하게 움직이는 상태.
    - 흐림 (Cloudy): 투자 심리가 위축되어 지수가 정체되거나 소폭 하락하는 상태.
    - 비 (Rainy): 국채금리나 환율 상승 등 악재로 인해 시장이 전반적으로 하락하는 상태.
    - 태풍 (Stormy): 급격한 지수 폭락, VIX지수 폭등 등 시장에 큰 공포가 확산된 상태.

    [온도 기준 가이드]
    - 30도 이상: 시장이 매우 뜨겁게 과열된 상태 (강한 상승장)
    - 15도 ~ 25도: 적당히 따뜻하고 활기찬 상태 (완만한 상승/안정)
    - 0도 ~ 10도: 썰렁하고 기운 없는 상태 (정체/약보합)
    - 영하: 시장이 차갑게 식어버린 상태 (급락/공포)

    [요청 사항]
    1. 지표들의 움직임을 종합하여 오늘의 날씨 상태를 선택하고, 그에 어울리는 '온도'를 설정하세요.
    2. '기상 브리핑'을 2-3문장으로 아주 쉽게 작성해 주세요. 지표의 움직임을 찬바람, 햇살, 소나기 등 날씨 용어로 비유하세요.
    3. 국내 지표(KOSPI, KOSDAQ)와 해외 지표의 연관성을 고려하여 분석해 주세요.
    4. 각 지표에 대한 짧은 코멘트를 포함하세요.
    5. 부드럽고 친절한 기상캐스터 말투를 사용하세요 (~입니다, ~네요).

    [JSON 형식]
    {{
        "weather": "맑음 | 구름조금 | 흐림 | 비 | 태풍",
        "temperature": "00C",
        "title": "기상 특보 한줄 요약",
        "briefing": "전체적인 시장 날씨 설명",
        "details": [
            {{"name": "S&P 500", "status": "맑음/흐림", "comment": "코멘트"}},
            ...
        ]
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        return None

def update_db(weather_report):
    print("Updating Supabase market_weather table...")
    data = {
        "weather": weather_report['weather'],
        "temperature": weather_report['temperature'],
        "title": weather_report['title'],
        "briefing": weather_report['briefing'],
        "details": weather_report['details'],
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        # 최근 상태 하나만 유지 (id=1)
        data['id'] = 1
        result = supabase.table("market_weather").upsert(data).execute()
        print("Successfully updated market weather!")
        return result
    except Exception as e:
        print(f"Error updating Supabase: {e}")
        return None

if __name__ == "__main__":
    indices = get_market_indices()
    if indices:
        report = analyze_weather(indices)
        if report:
            update_db(report)
