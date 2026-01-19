import os
import json
import yfinance as yf
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_kospi_data():
    print("Fetching KOSPI data...")
    try:
        ticker = yf.Ticker("^KS11")
        # 최근 1년치 데이터를 가져와서 지표 계산
        hist = ticker.history(period="1y")
        
        if hist.empty:
            return None
            
        current_price = hist['Close'].iloc[-1]
        
        # 1. Price Momentum (125-day Moving Average)
        ma125 = hist['Close'].rolling(window=125).mean().iloc[-1]
        momentum = (current_price / ma125) if not pd.isna(ma125) else 1.0
        
        # 2. Price Strength (52-week High/Low)
        low_52w = hist['Close'].min()
        high_52w = hist['Close'].max()
        strength_rank = (current_price - low_52w) / (high_52w - low_52w) * 100
        
        # 3. Volatility (20-day standard deviation)
        returns = hist['Close'].pct_change().dropna()
        volatility_20d = returns.tail(20).std()
        volatility_avg = returns.std()
        volatility_ratio = volatility_20d / volatility_avg if volatility_avg != 0 else 1.0
        
        # 4. Recent Change
        change_1d = ((current_price - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100) if len(hist) > 1 else 0
        
        return {
            "current_price": round(current_price, 2),
            "ma125": round(ma125, 2) if not pd.isna(ma125) else None,
            "momentum_ratio": round(momentum, 4),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "strength_rank": round(strength_rank, 2),
            "volatility_ratio": round(volatility_ratio, 4),
            "change_1d": round(change_1d, 2)
        }
    except Exception as e:
        print(f"Error fetching KOSPI data: {e}")
        return None

def analyze_kospi_sentiment(kospi_data):
    print("Analyzing KOSPI sentiment with AI...")
    
    prompt = f"""
    당신은 한국 주식 시장(KOSPI) 분석 전문가입니다. 
    제공된 기술적 지표를 바탕으로 현재 코스피의 '공포와 탐욕 지수(Fear & Greed Index)'를 산출하고 분석해 주세요.

    [코스피 데이터]
    - 현재가: {kospi_data['current_price']}
    - 125일 이동평균선 대비: {kospi_data['momentum_ratio']} (1보다 크면 상승세)
    - 52주 고점 대비 위치: {kospi_data['strength_rank']}% (0: 최저점, 100: 최고점)
    - 변동성 비율: {kospi_data['volatility_ratio']} (1보다 크면 최근 변동성 확대)
    - 전일 대비 등락: {kospi_data['change_1d']}%

    [요청 사항]
    1. 위 데이터를 종합하여 0~100 사이의 '공포와 탐욕 지수' 값을 정하세요.
       - 0~25: 극도의 공포 (Extreme Fear)
       - 26~45: 공포 (Fear)
       - 46~55: 중립 (Neutral)
       - 56~75: 탐욕 (Greed)
       - 76~100: 극도의 탐욕 (Extreme Greed)
    2. 현재 시장의 심리 상태를 한국 시장 특유의 상황(외인/기관 수급, 최근 이슈 등 추정 가능할 경우)을 고려하여 쉽게 설명해 주세요.
    3. 가독성이 좋은 3~4개의 짧은 문장으로 분석(analysis)을 작성해 주세요.
    4. 투자자가 가져야 할 조언(advice) 3가지를 친절하고 부드러운 말투로 작성해 주세요.
    5. 전체적으로 "오늘 국장 분위기는 이렇습니다"라고 브리핑하는 톤앤매너를 유지해 주세요.
    6. 중립적인 해석을 해주세요.
    7. 차분한 말투로 작성해 주세요.
    8. 조언할땐 ~하세요가 아닌 ~하는것이 좋아보여요, ~하는게 어때요? 등의 부드러운 어투를 사용해 주세요.
    9. 높임말 사용.
    10. 조언 1에선 조언 2,3과 다르게 문장에 알맞는 이모지 작성, 35자 이내로 간결하게 작성.
    11. 사용자가 네 의견만 맹신하여 따라하지 않도록 문장을 작성
    12. JSON 형식으로만 응답하세요.

    [JSON 형식]
    {{
        "value": 00,
        "description": "상태(영문 및 한글 병기, 예: Greed (탐욕))",
        "title": "요약 제목",
        "analysis": "분석 내용 (줄바꿈 포함)",
        "advice": ["조언1", "조언2", "조언3"]
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        res_data = json.loads(response.text)
        return res_data
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        return {
            "value": 50,
            "description": "Neutral (중립)",
            "title": "분석을 불러올 수 없습니다.",
            "analysis": "현재 AI 분석 기능에 일시적인 문제가 발생했습니다.",
            "advice": ["시장의 기본 지표를 참고해 주세요."]
        }

def update_db(ai_analysis):
    print("Updating Supabase fear_greed table for KOSPI (id=2)...")
    data = {
        "id": 2, # KOSPI 전용 ID
        "value": ai_analysis['value'],
        "description": ai_analysis['description'],
        "title": ai_analysis['title'],
        "analysis": ai_analysis['analysis'],
        "advice": ai_analysis['advice'],
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        result = supabase.table("fear_greed").upsert(data).execute()
        print("Successfully updated KOSPI Fear & Greed Index!")
        return result
    except Exception as e:
        print(f"Error updating Supabase: {e}")
        return None

if __name__ == "__main__":
    kospi_data = get_kospi_data()
    if kospi_data:
        analysis = analyze_kospi_sentiment(kospi_data)
        update_db(analysis)
    else:
        print("Failed to fetch KOSPI data.")
