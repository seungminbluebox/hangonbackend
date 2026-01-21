import os
import json
import yfinance as yf
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
from config import GEMINI_MODEL_NAME

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY =  os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MODEL_NAME = GEMINI_MODEL_NAME

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(MODEL_NAME)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_kospi_data():
    print("Fetching KOSPI 7-Indicator Data...")
    try:
        # 1. 기초 데이터 수집
        kospi = yf.Ticker("^KS11").history(period="1y")
        kosdaq = yf.Ticker("^KQ11").history(period="1y")
        gold = yf.Ticker("GC=F").history(period="1y")
        # 한국형 풋/콜 대용: 레버리지(069500) vs 인버스(252670) 거래량
        bull_etf = yf.Ticker("069500.KS").history(period="1mo")
        bear_etf = yf.Ticker("252670.KS").history(period="1mo")
        
        if kospi.empty: return None
        
        # --- [7대 지표 계산] ---
        
        # X1. Market Momentum (주가 모멘텀)
        ma125 = kospi['Close'].rolling(window=125).mean().iloc[-1]
        x1 = 100 if kospi['Close'].iloc[-1] > ma125 else 0
        
        # X2. Stock Price Strength (주가 강도)
        low_52w = kospi['Close'].min()
        high_52w = kospi['Close'].max()
        x2 = (kospi['Close'].iloc[-1] - low_52w) / (high_52w - low_52w) * 100
        
        # X3. Stock Price Breadth (시장 폭)
        avg_vol = kospi['Volume'].rolling(window=20).mean().iloc[-1]
        x3 = min(100, (kospi['Volume'].iloc[-1] / avg_vol) * 50) if avg_vol > 0 else 50
        
        # X4. Put and Call Options (옵션 수요)
        if not bull_etf.empty and not bear_etf.empty:
            ratio = bull_etf['Volume'].iloc[-1] / bear_etf['Volume'].iloc[-1]
            x4 = min(100, ratio * 50)
        else:
            x4 = 50
            
        # X5. Junk Bond Demand (정크본드 수요) - KOSDAQ vs KOSPI 상대강도
        rel_strength = (kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-20]) / \
                       (kospi['Close'].iloc[-1] / kospi['Close'].iloc[-20])
        x5 = max(0, min(100, (rel_strength - 0.9) * 500))
        
        # X6. Market Volatility (시장 변동성)
        vol = kospi['Close'].pct_change().rolling(window=20).std().iloc[-1]
        vol_avg = kospi['Close'].pct_change().std()
        x6 = max(0, min(100, 100 - (vol / vol_avg - 1) * 100)) if vol_avg > 0 else 50
        
        # X7. Safe Haven Demand (안전자산 선호) - 주식 vs 금 수익률 차이
        stock_ret = kospi['Close'].pct_change(20).iloc[-1]
        gold_ret = gold['Close'].pct_change(20).iloc[-1] if not gold.empty else 0
        x7 = max(0, min(100, 50 + (stock_ret - gold_ret) * 500))

        return {
            "value": round((x1 + x2 + x3 + x4 + x5 + x6 + x7) / 7, 2),
            "indicators": {
                "x1": round(x1, 2),
                "x2": round(x2, 2),
                "x3": round(x3, 2),
                "x4": round(x4, 2),
                "x5": round(x5, 2),
                "x6": round(x6, 2),
                "x7": round(x7, 2)
            },
            "current_price": round(kospi['Close'].iloc[-1], 2),
            "change_1d": round(((kospi['Close'].iloc[-1] - kospi['Close'].iloc[-2]) / kospi['Close'].iloc[-2] * 100), 2)
        }
    except Exception as e:
        print(f"Error fetching KOSPI data: {e}")
        return None

def analyze_kospi_sentiment(kospi_data):
    print("Analyzing KOSPI sentiment with AI...")
    
    prompt = f"""
    당신은 한국 주식 시장(KOSPI) 분석 전문가입니다. 
    CNN Business의 7대 공포와 탐욕 지표 공식에 따라 산출된 결과를 분석해 주세요.

    [실시간 7대 지표 점수 (0~100)]
    1. 주가 모멘텀 (Market Momentum): {kospi_data['indicators']['x1']}
    2. 주가 강도 (Stock Price Strength): {kospi_data['indicators']['x2']}
    3. 시장 폭 (Stock Price Breadth): {kospi_data['indicators']['x3']}
    4. 옵션 수요 (Put and Call Options): {kospi_data['indicators']['x4']}
    5. 정크본드 수요 (Junk Bond Demand): {kospi_data['indicators']['x5']}
    6. 시장 변동성 (Market Volatility): {kospi_data['indicators']['x6']}
    7. 안전자산 선호 (Safe Haven Demand): {kospi_data['indicators']['x7']}

    - 최종 산출 지수 값: {kospi_data['value']}

    [요청 사항]
    1. 아래 기준에 맞춰 최종 지수 값에 알맞은 상태(description)를 선택하세요:
       - 0~25: Extreme Fear (극도의 공포)
       - 26~45: Fear (공포)
       - 46~55: Neutral (중립)
       - 56~75: Greed (탐욕)
       - 76~100: Extreme Greed (극도의 탐욕)
    2. 현재 한국 시장의 수급(외인/기관)과 매크로 환경을 고려하여 분석(analysis)을 3~4문장으로 작성해 주세요.
    3. 투자자 조언(advice) 3가지를 친절하고 부드럽게 작성해 주세요.
    4. 조언 1에는 적절한 이모지를 포함하고 35자 이내로 작성.
    5. 한글로 작성해 주세요.
    6. 중립적인 해석을 해주세요.
    7. 분석(analysis) 내용은 긴 줄글이 아닌, 가독성이 좋은 3~4개의 짧은 문장 또는 불렛 포인트 형식으로 작성해 주세요.
    8. 전체적으로 "오늘 시장 분위기는 이렇습니다"라고 가볍게 브리핑하는 톤앤매너를 유지해 주세요.
    9. 차분한 말투로 작성해 주세요.
    10. 조언할땐 ~하세요가 아닌 ~하는것이 좋아보여요, ~하는게 어때요? 등의 부드러운 어투를 사용해 주세요.
    11. 높임말 사용.
    12. 조언 1에선 조언 2,3과 다르게 문장에 알맞는 이모지 작성, 35자 이내로 간결하게 작성.
    13. 사용자가 네 의견만 맹신하여 따라하지 않도록 문장을 작성
    14. JSON 형식으로만 응답하세요.
    15. title은 현재 시장 심리를 한 문장으로 요약한 제목으로 작성해 주세요. (~,-,! 사용금지)
    16. 특수문자 **같은 물결표는 사용 금지**입니다. 텍스트만 작성해 주세요.
    [JSON 형식]
    {{
        "value": {kospi_data['value']},
        "description": "상태(한글로)",
        "title": "요약 제목",
        "analysis": "분석 내용",
        "advice": ["조언1", "조언2", "조언3"]
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        res_data = json.loads(response.text)
        if isinstance(res_data, list):
            return res_data[0]
        return res_data
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        return {
            "value": 50,
            "description": "중립",
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
