import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
import yfinance as yf
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
from config import GEMINI_MODEL_NAME
from news.push_notification import send_push_notification

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MODEL_NAME = GEMINI_MODEL_NAME

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(MODEL_NAME)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 분석할 티커 정의
TICKERS = {
    "Domestic": {
        "Index": {
            "KOSPI": "^KS11",
            "KOSDAQ": "^KQ11"
        },
        "Sectors": {
            "반도체": "091160.KS", # KODEX 반도체
            "바이오": "261220.KS", # KODEX 바이오
            "2차전지": "305720.KS", # KODEX 2차전지산업
            "은행": "091170.KS", # KODEX 은행
            "방산": "461580.KS", # KODEX K-방산
            "IT/게임": "091180.KS", # KODEX IT
            "철강/소재": "117680.KS", # KODEX 철강
            "조선": "466940.KS" # KODEX 조선
        }
    },
    "US": {
        "Index": {
            "S&P500": "^GSPC",
            "NASDAQ": "^IXIC",
            "다우존스": "^DJI",
            "러셀2000": "^RUT"
        },
        "Sectors": {
            "기술주(XLK)": "XLK",
            "반도체(SOXX)": "SOXX",
            "금융(XLF)": "XLF",
            "헬스케어(XLV)": "XLV",
            "소비재(XLY)": "XLY",
            "에너지(XLE)": "XLE",
            "산업재(XLI)": "XLI",
            "커뮤니케이션(XLC)": "XLC"
        }
    },
    "Safe": {
        "Risk": {
            "비트코인": "BTC-USD",
            "나스닥(QQQ)": "QQQ",
            "구리 선물": "HG=F"
        },
        "Safe": {
            "금 선물": "GC=F",
            "달러 인덱스(UUP)": "UUP",
            "미 국채(TLT)": "TLT"
        }
    }
}

def get_flow_data(category_tickers):
    print(f"Fetching Data for category...")
    results = {}
    
    for subcat, tickers in category_tickers.items():
        results[subcat] = {}
        for name, symbol in tickers.items():
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="20d")
                if hist.empty:
                    # Alternative fetch for some ETFs
                    hist = ticker.history(period="1mo")
                    if hist.empty: continue
                
                # 전일 대비 등락률
                current_price = hist['Close'].iloc[-1]
                prev_price = hist['Close'].iloc[-2]
                change_pct = ((current_price - prev_price) / prev_price) * 100
                
                # 상대 거래량 (20일 평균 대비)
                current_vol = hist['Volume'].iloc[-1]
                avg_vol = hist['Volume'].mean()
                rel_vol = (current_vol / avg_vol) if avg_vol > 0 else 1
                
                results[subcat][name] = {
                    "symbol": symbol,
                    "price": float(round(current_price, 2)),
                    "change": float(round(change_pct, 2)),
                    "rel_vol": float(round(rel_vol, 2))
                }
            except Exception as e:
                print(f"Error fetching {name} ({symbol}): {e}")
                
    return results

def analyze_money_flow(flow_data, type_name):
    print(f"Analyzing {type_name} Money Flow with AI...")
    
    prompts = {
        "Domestic": "한국 증시(코스피, 코스닥)와 주요 업무 섹터별 자금 흐름을 분석하세요.",
        "US": "미국 증시(S&P500, 나스닥, 다우존스, 러셀2000)와 주요 섹터별 자금 흐름을 분석하세요.",
        "Safe": "비트코인, 나스닥, 구리(위험자산)와 금, 달러, 국채(안전자산) 간의 자금 이동 및 글로벌 매크로 심리를 분석하세요."
    }

    # Safe 타입일 경우 추가 가이드 제공
    analysis_guide = ""
    if type_name == "Safe":
        analysis_guide = "위험자산(Risk) 그룹과 안전자산(Safe) 그룹 중 어느 쪽에 더 '진짜 돈(거래량)'이 실리고 있는지 비교 분석하고, 현재 시장이 Risk-On(위험 선호)인지 Risk-Off(안전 선호)인지 명확히 진단하세요."

    prompt = f"""
    당신은 금융 시장의 자금 흐름을 분석하는 수석 전략가입니다. 
    다음 데이터를 바탕으로 현재 시장에서 '돈이 어디로 이동하고 있는지' 분석해 주세요.
    분석 대상: {prompts.get(type_name, type_name)}
    {analysis_guide}
    
    데이터:
    {json.dumps(flow_data, indent=2, ensure_ascii=False)}
    
    분석 기준:
    1. 해당 영역에서 현재 돈이 쏠리는 곳과 빠져나가는 곳은 어디인가?
    2. 거래량(rel_vol)이 높은 항목과 가격 변동(change)을 결합하여 '진짜 돈의 움직임'을 포착하세요.
    3. 전반적인 심리와 내일부터의 대응 전략을 요약하세요.
    4. 느낌표, 물결표같은 감정표현 금지. 보고하는 차분한 말투로 작성.
    5. 조언은 신중하게, 사용자가 맹신하지 않도록 작성.
    6. 특수문자 **같은 기호는 절대 사용 금지.
    7. ~하세요보단 ~를 권장합니다 같은 어투를 사용.
    결과는 반드시 아래 JSON 형식으로만 출력하세요:
    {{
      "summary": "자금 흐름의 핵심을 한 줄로 요약",
      "analysis": "핵심 분석 (3문장 이내, 간결하고 차분하게)",
      "strategy": ["투자 전략 1", "전략 2", "전략 3"]
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
        
        return json.loads(text.strip())
    except Exception as e:
        print(f"AI Analysis Error for {type_name}: {e}")
        return None

def main():
    category_map = {
        "Domestic": 1,
        "US": 2,
        "Safe": 3
    }
    
    for cat_name, cat_id in category_map.items():
        print(f"\n--- Processing {cat_name} ---")
        flow_data = get_flow_data(TICKERS[cat_name])
        if not flow_data:
            print(f"No data for {cat_name}")
            continue
            
        analysis_res = analyze_money_flow(flow_data, cat_name)
        if not analysis_res:
            print(f"Analysis failed for {cat_name}")
            continue
            
        data_to_upsert = {
            "id": cat_id,
            "flow_data": flow_data,
            "summary": analysis_res.get("summary"),
            "analysis": analysis_res.get("analysis"),
            "strategy": analysis_res.get("strategy"),
            "updated_at": datetime.now().isoformat()
        }
        
        try:
            supabase.table("money_flow").upsert(data_to_upsert).execute()
            print(f"Successfully updated {cat_name} Money Flow (ID: {cat_id})")
        except Exception as e:
            print(f"Error updating Supabase for {cat_name}: {e}")
            
    # 모든 카테고리 업데이트 완료 후 푸시 알림 (카테고리: us_money_flow)
    try:
        send_push_notification(
            title="💰 실시간 자금 흐름 분석 완료",
            body="국내/미국 증시 및 안전자산 간의 돈의 움직임을 분석했습니다. 지금 확인해보세요.",
            url="/money-flow",
            category="us_money_flow"
        )
    except Exception as e:
        print(f"Failed to send push: {e}")

if __name__ == "__main__":
    main()
