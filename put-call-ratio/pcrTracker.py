import os
import sys
import time
import re
import json
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client, Client
import google.generativeai as genai
from dotenv import load_dotenv

# 상위 디렉토리 참조
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import GEMINI_MODEL_NAME

load_dotenv()

# 환경 변수
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL_NAME)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_latest_pcr_data(days_to_check=5):
    """
    최근 N일간의 CBOE 데이터를 확인하여 새로운 데이터를 수집합니다.
    """
    print("🕵️ CBOE에서 최신 PCR 데이터 수집을 시작합니다...")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    chrome_options.add_argument("--log-level=3")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    collected_data = []
    
    # 오늘 포함 최근 N일 체크
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_to_check)
    date_range = pd.date_range(start=start_date, end=end_date, freq='B')
    dates = date_range.strftime("%Y-%m-%d").tolist()

    try:
        for date_str in reversed(dates): # 최신 날짜부터 역순으로
            url = f"https://www.cboe.com/us/options/market_statistics/daily/?dt={date_str}"
            try:
                driver.get(url)
                time.sleep(2) # 로딩 대기
                
                body_text = driver.find_element(By.TAG_NAME, "body").text
                
                def extract(keyword):
                    match = re.search(re.escape(keyword) + r"\s*([\d\.]+)", body_text, re.IGNORECASE)
                    return float(match.group(1)) if match else None

                total = extract("TOTAL PUT/CALL RATIO")
                index = extract("INDEX PUT/CALL RATIO")
                equity = extract("EQUITY PUT/CALL RATIO")
                
                if total is not None:
                    print(f"✅ {date_str} 데이터 수집 성공: {total}")
                    collected_data.append({
                        'date': date_str,
                        'total': total,
                        'index': index,
                        'equity': equity
                    })
                else:
                    print(f"ℹ️ {date_str} 데이터 없음 (휴장일 또는 미게시)")
            except Exception as e:
                print(f"⚠️ {date_str} 수집 중 에러: {e}")
                
    finally:
        driver.quit()

    return collected_data

def sync_to_supabase(data_list):
    if not data_list:
        return
    
    print(f"📤 {len(data_list)}개의 데이터를 Supabase에 동기화 중...")
    try:
        supabase.table("pcr_history").upsert(data_list).execute()
        print("✅ PCR 히스토리 업데이트 완료")
    except Exception as e:
        print(f"❌ Supabase 동기화 에러: {e}")

def analyze_pcr_sentiment(history_df):
    if history_df.empty:
        return None
    
    # 최신 데이터 (전날 기준)
    latest = history_df.iloc[-1]
    prev = history_df.iloc[-2] if len(history_df) > 1 else latest
    
    # 15일간의 요약 데이터 준비
    recent_15 = history_df.tail(15).to_dict(orient='records')
    
    print("🤖 AI에게 시장 심리 분석 요청 중 (최근 15일 데이터)...")
    
    prompt = f"""
    당신은 옵션 시장의 흐름을 통해 증시 심리를 분석하는 전문 전략가입니다.
    CBOE의 Put/Call Ratio(PCR) 데이터를 바탕으로 현재 시장의 공포와 탐욕 지수를 분석해 주세요.
    
    최근 15일간의 데이터:
    {json.dumps(recent_15, indent=2)}
    
    분석 기준:
    1. Total PCR이 1.0보다 높으면 '공포/바닥권', 0.7보다 낮으면 '과열/고점권'으로 해석합니다.
    2. 전날({prev['date']}) 대비 오늘({latest['date']})의 변화가 어떤 의미를 갖는지 설명하세요.
    3. 최근 15일간의 흐름(추세)이 상승 중인지, 하락 중인지, 아니면 횡보 중인지 분석하세요.
    4. 분석은 철저히 객관적이고 차분한 보고서 문체로 작성하세요. (느낌표 금지)
    5. 현재 시장 상황에 대한 요약과 투자자에게 유용한 인사이트를 포함하세요.
    
    결과는 반드시 아래 JSON 형식으로 반환하세요:
    {{
      "title": "현재의 시장 심리를 요약하는 제목 (이모지 포함)",
      "summary": "핵심 요약 한 문장",
      "analysis": "오늘의 지표 분석과 최근 15일간의 추세 분석 (3~4문장 정도)",
      "recommendation": ["투자자가 참고해야 할 포인트 1", "포인트 2", "포인트 3"]
    }}
    
    반드시 유효한 JSON이어야 하며, 한국어로 답변하세요.
    """
    
    try:
        # 안전 설정 및 생성 설정 추가
        generation_config = {
            "temperature": 0.2,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 1024,
            "response_mime_type": "application/json",
        }
        
        response = model.generate_content(prompt, generation_config=generation_config)
        
        if not response or not response.candidates:
            print("❌ AI 분석 에러: 응답 후보가 없습니다.")
            return None
            
        text = response.text.strip()
        
        # 만약 response_mime_type이 적용되지 않아 백틱이 포함된 경우 대비
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        return json.loads(text)
    except json.JSONDecodeError as je:
        print(f"❌ JSON 파싱 에러: {je}")
        print(f"원본 텍스트: {text}")
        return None
    except Exception as e:
        print(f"❌ AI 분석 에러: {e}")
        return None

def update_analysis(analysis_data, flow_data):
    if not analysis_data:
        return
        
    payload = {
        "id": 1,
        "title": analysis_data.get("title"),
        "summary": analysis_data.get("summary"),
        "analysis": analysis_data.get("analysis"),
        "recommendation": analysis_data.get("recommendation"),
        "latest_data": flow_data,
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        supabase.table("pcr_analysis").upsert(payload).execute()
        print("✅ PCR 분석 결과 업데이트 완료")
    except Exception as e:
        print(f"❌ 분석 결과 저장 에러: {e}")
        print("\n[SQL] pcr_analysis 테이블이 없을 수 있습니다:")
        print("""
        CREATE TABLE pcr_analysis (
            id BIGINT PRIMARY KEY,
            title TEXT,
            summary TEXT,
            analysis TEXT,
            recommendation JSONB,
            latest_data JSONB,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """)

def main():
    # 1. 최신 데이터 수집 (최근 20일치를 확인하여 빠진 데이터를 보충)
    new_data = get_latest_pcr_data(days_to_check=20)
    
    # 2. Supabase에 저장
    if new_data:
        sync_to_supabase(new_data)
    
    # 3. 전체 히스토리 가져오기 (분석용)
    try:
        res = supabase.table("pcr_history").select("*").order("date", desc=False).execute()
        history_df = pd.DataFrame(res.data)
        
        if not history_df.empty:
            # 4. AI 분석
            analysis_res = analyze_pcr_sentiment(history_df)
            
            # 5. 분석 결과 저장 (최신 데이터 포함)
            latest_data = history_df.iloc[-1].to_dict()
            update_analysis(analysis_res, latest_data)
            
    except Exception as e:
        print(f"❌ 데이터 로드 및 분석 중 에러: {e}")

if __name__ == "__main__":
    main()
