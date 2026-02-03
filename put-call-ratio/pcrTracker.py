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
from google import genai
from dotenv import load_dotenv

# 상위 디렉토리 참조 (로컬 config.py 우선권을 위해 sys.path 맨 앞에 추가)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from news.push_notification import send_push_to_all
from config import GEMINI_MODEL_NAME

load_dotenv()

# 환경 변수
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

client = genai.Client(api_key=GOOGLE_API_KEY)
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
    
    # 최신 데이터
    latest = history_df.iloc[-1]
    
    # 최근 15일간의 데이터 준비
    recent_15 = history_df.tail(15).to_dict(orient='records')
    
    print("Analyzing PCR Sentiment with AI...")
    
    prompt = f"""
    당신은 옵션 시장의 흐름을 분석하는 수석 전략가입니다. 
    다음 CBOE Put/Call Ratio 데이터를 바탕으로 현재 시장 심리를 분석해 주세요.
    
    데이터:
    {json.dumps(recent_15, indent=2, ensure_ascii=False)}
    
    분석 기준:
    1. Total PCR이 1.0보다 높으면 '공포/바닥권', 0.7보다 낮으면 '과열/고점권'으로 해석.
    2. 최근 15일간의 흐름이 상승(공포 심화)인지 하락(탐욕 심화)인지 분석.
    3. 전반적인 시장 심리와 향후 대응 전략을 요약하세요.
    4. 느낌표, 물결표같은 감정표현 금지 높은사람한테 보고하는 차분한 말투로 작성.
    5. ~해라라는 단언적인 조언보단, 사용자가 네 의견만 맹신하여 따라하지 않도록 문장을 작성
    6. 특수문자 **같은 물결표는 사용 금지**입니다. 텍스트만 작성해 주세요.

    결과는 반드시 아래 JSON 형식으로만 출력하세요:
    {{
      "title": "오늘의 시장 심리를 요약하는 제목과 문장에 적합한 이모지하나 사용",
      "summary": "시장 심리의 핵심을 한 줄로 요약",
      "analysis": "현재 심리에 대한 핵심 분석 (핵심만 3문장 이내로 아주 간결하게 작성, 높은사람한테 보고하는 말투)",
      "recommendation": ["투자자가 실천할 수 있는 전략 1", "전략 2", "전략 3"]
    }}
    
    반드시 유효한 JSON 형식이어야 하며, 한국어로 답변하세요.
    """
    
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt
        )
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
            
            # 푸시 알림 전송
            try:
                send_push_to_all(
                    title="⚖️ 시장 심리 지표(PCR) 업데이트",
                    body="풋/콜 옵션 비율 분석이 완료되었습니다. 현재 투자자들의 심리를 확인하세요.",
                    url="/put-call-ratio"
                )
            except Exception as e:
                print(f"Failed to send push: {e}")
            
    except Exception as e:
        print(f"❌ 데이터 로드 및 분석 중 에러: {e}")

if __name__ == "__main__":
    main()
