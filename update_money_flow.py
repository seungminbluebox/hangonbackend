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

# 분석할 티커 정의
TICKERS = {
    "Risk": {
        "KOSPI": "^KS11",
        "S&P500": "^GSPC",
        "NASDAQ": "^IXIC",
        "Bitcoin": "BTC-USD"
    },
    "Safe": {
        "Gold": "GC=F",
        "USD/KRW": "KRW=X",
        "US 10Y Yield": "^TNX"
    },
    "Sectors": {
        "반도체": "091160.KS",   # KODEX 반도체
        "바이오": "261220.KS",       # KODEX 바이오
        "2차전지": "305720.KS",   # KODEX 2차전지산업
        "은행": "091170.KS",      # KODEX 은행
        "방산": "461580.KS",      # KODEX K-방산 (대체)
        "IT/게임": "091180.KS"    # KODEX IT
    }
}

def get_flow_data():
    print("Fetching Money Flow Data...")
    results = {}
    
    for category, tickers in TICKERS.items():
        results[category] = {}
        for name, symbol in tickers.items():
            try:
                ticker = yf.Ticker(symbol)
                # 상대 거래량 계산을 위해 20일치 가져옴
                hist = ticker.history(period="20d")
                if hist.empty:
                    if category == "Sectors": # ETF는 가끔 데이터 안나올 때 있음
                        ticker = yf.Ticker(symbol)
                        hist = ticker.history(period="1mo")
                    if hist.empty: continue
                
                # 전일 대비 등락률
                current_price = hist['Close'].iloc[-1]
                prev_price = hist['Close'].iloc[-2]
                change_pct = ((current_price - prev_price) / prev_price) * 100
                
                # 상대 거래량 (20일 평균 대비) - 돈의 쏠림 지표
                current_vol = hist['Volume'].iloc[-1]
                avg_vol = hist['Volume'].mean()
                rel_vol = (current_vol / avg_vol) if avg_vol > 0 else 1
                
                results[category][name] = {
                    "symbol": symbol,
                    "price": float(round(current_price, 2)),
                    "change": float(round(change_pct, 2)),
                    "rel_vol": float(round(rel_vol, 2))
                }
            except Exception as e:
                print(f"Error fetching {name} ({symbol}): {e}")
                
    return results

def analyze_money_flow(flow_data):
    print("Analyzing Money Flow with AI...")
    
    prompt = f"""
    당신은 금융 시장의 자금 흐름을 분석하는 수석 전략가입니다. 
    다음 데이터를 바탕으로 현재 시장에서 '돈이 어디로 이동하고 있는지' 분석해 주세요.
    
    데이터:
    {json.dumps(flow_data, indent=2, ensure_ascii=False)}
    
    분석 기준:
    1. 위험 자산(주식, 코인) vs 안전 자산(금, 달러, 국채금리) 중 어디로 돈이 쏠리는가?
    2. 한국 섹터 ETF 데이터 중 어떤 업종의 상대 거래량(rel_vol)이 높고 수익률이 좋은가? (진짜 돈이 쏠리는 곳)
    3. 전반적인 시장의 심리와 내일부터의 대응 전략을 요약하세요.
    
    결과는 반드시 아래 JSON 형식으로만 출력하세요:
    {{
      "title": "오늘의 돈의 향방을 요약하는 짧고 강렬한 제목",
      "summary": "자금 흐름의 핵심을 한 줄로 요약",
      "analysis": "현재 자금 흐름에 대한 핵심 분석 (핵심만 3문장 이내로 아주 간결하게 작성, 높은사람한테 보고하는 말투)",
      "strategy": ["투자자가 실천할 수 있는 전략 1", "전략 2", "전략 3"]
    }}
    
    반드시 유효한 JSON 형식이어야 하며, 한국어로 답변하세요.
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        res_data = json.loads(text.strip())
        return res_data
    except Exception as e:
        print(f"AI Analysis Error: {e}")
        return None

def main():
    flow_data = get_flow_data()
    if not flow_data:
        print("No data collected.")
        return
        
    analysis_res = analyze_money_flow(flow_data)
    if not analysis_res:
        print("Analysis failed.")
        return
        
    # Supabase 업데이트
    data_to_upsert = {
        "id": 1,
        "flow_data": flow_data,
        "title": analysis_res.get("title"),
        "summary": analysis_res.get("summary"),
        "analysis": analysis_res.get("analysis"),
        "strategy": analysis_res.get("strategy"),
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        # upsert 시도
        supabase.table("money_flow").upsert(data_to_upsert).execute()
        print("Successfully updated Money Flow Tracker!")
    except Exception as e:
        print(f"Error updating Supabase: {e}")
        print("\n[알림] 'money_flow' 테이블이 없는 경우 Supabase SQL Editor에서 다음 명령어를 실행해주세요:")
        print("""
        CREATE TABLE money_flow (
            id BIGINT PRIMARY KEY,
            flow_data JSONB,
            title TEXT,
            summary TEXT,
            analysis TEXT,
            strategy JSONB,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """)

if __name__ == "__main__":
    main()
