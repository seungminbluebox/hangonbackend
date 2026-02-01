import os
import sys
import time
import json
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from supabase import create_client, Client
import google.generativeai as genai
from dotenv import load_dotenv

# 상위 디렉토리 참조
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import GEMINI_MODEL_NAME
from news.push_notification import send_push_to_all

load_dotenv()

# 환경 변수
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL_NAME)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_credit_balance_history(pages=10):
    """
    네이버 증권에서 신용융자 잔고 히스토리를 수집합니다.
    1페이지당 약 15~20일치 데이터가 있습니다. 10페이지면 약 1년치(영업일 기준)를 가져옵니다.
    """
    print(f"🌍 네이버 증권에서 신용융자 잔고 수집 중 (페이지: {pages})...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    collected_data = []
    
    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/sise/sise_deposit.naver?page={page}"
        try:
            response = requests.get(url, headers=headers)
            response.encoding = 'euc-kr'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 데이터 테이블 찾기
            table = soup.find('table', {'class': 'type_1'})
            if not table:
                continue
                
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 5:
                    date_str = cols[0].text.strip()
                    if not date_str or '.' not in date_str:
                        continue
                    
                    # 날짜 형식 변환 (25.01.24 -> 2025-01-24)
                    try:
                        # Naver는 보통 YY.MM.DD 형식을 사용함
                        date = datetime.strptime(date_str, "%y.%m.%d").strftime("%Y-%m-%d")
                    except ValueError:
                        try:
                            # 혹시 모를 YYYY.MM.DD 형식 대응
                            date = datetime.strptime(date_str, "%Y.%m.%d").strftime("%Y-%m-%d")
                        except ValueError:
                            continue
                    
                    # 날짜 | 고객예탁금 | 대비 | 신용융자 | 대비 ... 순서임
                    try:
                        # 고객예탁금 (2번째 컬럼 - 인덱스 1)
                        deposit = int(cols[1].text.strip().replace(',', '')) * 100000000
                        # 신용융자 합계 (4번째 컬럼 - 인덱스 3)
                        total = int(cols[3].text.strip().replace(',', '')) * 100000000
                        
                        collected_data.append({
                            'date': date,
                            'customer_deposit': deposit,
                            'total': total
                        })
                    except (ValueError, IndexError):
                        continue
            
            time.sleep(0.5) # 서버 부하 방지
        except Exception as e:
            print(f"⚠️ {page}페이지 수집 중 에러: {e}")
            
    return collected_data

def sync_to_supabase(data_list):
    if not data_list:
        return
    
    print(f"📤 {len(data_list)}개의 데이터를 Supabase에 동기화 중...")
    try:
        # 데이터가 많을 수 있으므로 upsert 사용
        supabase.table("credit_balance_history").upsert(data_list).execute()
        print("✅ 신용융자 히스토리 업데이트 완료")
    except Exception as e:
        print(f"❌ Supabase 동기화 에러: {e}")

def analyze_credit_sentiment(history_df):
    if history_df.empty:
        return None
    
    # 최신 데이터
    latest = history_df.iloc[-1]
    latest_total_trillion = latest['total'] / 1000000000000
    latest_deposit_trillion = latest['customer_deposit'] / 1000000000000
    ratio = (latest['total'] / latest['customer_deposit']) * 100
    
    # 최근 30일간의 데이터 준비
    recent_30 = history_df.tail(30).to_dict(orient='records')
    
    print("🤖 AI 분석 시작 (예탁금 대비 신용잔고 비율)...")
    
    prompt = f"""
    당신은 한국 주식 시장의 수석 전략가입니다. 
    다음 '고객예탁금(살 돈)'과 '신용융자 잔고(빌린 돈)' 데이터를 바탕으로 현재 시장의 기초 체력과 과열도를 분석해 주세요.
    
    데이터 (최신 30일):
    {json.dumps(recent_30, indent=2, ensure_ascii=False)}
    
    현재 상태:
    - 고객예탁금: {latest_deposit_trillion:.2f}조 원
    - 신용융자 잔고: {latest_total_trillion:.2f}조 원
    - 예탁금 대비 신용 비율: {ratio:.2f}%

    참고 분석 기준:
    1. 비율(신용/예탁금)이 20% 이하면 매우 안전 및 바닥권.
    2. 비율이 25% ~ 30% 수준이면 일반적인 수준.
    3. 비율이 35%를 넘어가면 시장의 실물 현금보다 빚의 속도가 빠른 과열권.
    4. 비율이 40%에 육박하면 하락 시 반대매매로 인한 폭락 리스크가 매우 큰 상태.
    
    분석 가이드:
    - 단순히 신용잔고가 높은 것보다, '예탁금이 따라와주고 있는지'를 중점적으로 분석하세요.
    - 예탁금은 줄어드는데 신용만 늘어나는 상황(괴리 발생)이라면 강한 경고를 보내세요.
    - '퍼센트' 또는 '퍼센트포인트'라는 단어 대신 반드시 '%' 기호를 사용하세요.
    - 분석(analysis)은 반드시 2~3문장으로 작성하되, 각 문장은 개행문자(\n)를 넣어 한 줄씩 끊어서 작성해 주세요.
    - 불필요한 서술은 생략하고, 한 눈에 들어오도록 매우 간결하게 작성하세요.
    - 느낌표, 물결표 금지. 전문성과 신뢰감이 느껴지는 간결한 문체 사용.
    - 특수문자 ** 사용 금지.
    - 투자 권유가 아닌 현상 분석임을 명확히 하되, 단언적인 표현은 피하세요.
    - 소수점 사용 금지

    결과 형식: 반드시 JSON 블록 하나만 출력하세요. 다른 텍스트는 금지합니다.
    JSON 구조 예시:
    {{
      "title": "시장 신용잔고 분석 1줄 요약",
      "summary": "안전/보통/과열 여부",
      "analysis": "분석 첫 번째 문장\n분석 두 번째 문장",
      "recommendation": ["액션 1", "액션 2", "액션 3"]
    }}
    """
    
    try:
        # 안전 설정 추가 (금융 분석 시 차단 방지)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        response = model.generate_content(prompt, safety_settings=safety_settings)
        
        # 응답 검증
        if not response.candidates or not response.candidates[0].content.parts:
            print(f"⚠️ AI 응답 생성 실패 (Finish Reason: {response.candidates[0].finish_reason if response.candidates else 'Unknown'})")
            return None
            
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

def update_analysis(analysis_data, latest_data):
    if not analysis_data:
        return
        
    # JSON 직렬화 시 NaN 처리
    clean_latest_data = {}
    for k, v in latest_data.items():
        if isinstance(v, float) and (pd.isna(v) or pd.isinf(v)):
            clean_latest_data[k] = 0
        else:
            clean_latest_data[k] = v

    payload = {
        "id": 1, # 고정 ID
        "title": analysis_data.get("title"),
        "summary": analysis_data.get("summary"),
        "analysis": analysis_data.get("analysis"),
        "recommendation": analysis_data.get("recommendation"),
        "latest_data": clean_latest_data,
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        supabase.table("credit_balance_analysis").upsert(payload).execute()
        print("✅ 신용융자 분석 결과 업데이트 완료")
    except Exception as e:
        print(f"❌ 분석 결과 저장 에러: {e}")

def get_latest_date_from_db():
    """DB에서 가장 최신 데이터의 날짜를 가져옵니다."""
    try:
        res = supabase.table("credit_balance_history").select("date").order("date", desc=True).limit(1).execute()
        if res.data:
            return res.data[0]['date']
    except Exception as e:
        print(f"⚠️ DB 날짜 확인 중 에러: {e}")
    return None

def get_latest_analysis_date_from_db():
    """DB에 저장된 가장 최신 분석의 기준 날짜를 가져옵니다."""
    try:
        res = supabase.table("credit_balance_analysis").select("latest_data").eq("id", 1).single().execute()
        if res.data and res.data.get('latest_data'):
            return res.data['latest_data'].get('date')
    except Exception as e:
        print(f"⚠️ 분석 날짜 확인 중 에러 (무시 가능): {e}")
    return None

def main():
    # 1. 각 테이블의 최신 날짜 확인
    latest_history_date = get_latest_date_from_db()
    latest_analysis_date = get_latest_analysis_date_from_db()
    
    print(f"📅 히스토리 최신 날짜: {latest_history_date}")
    print(f"🤖 마지막 분석 날짜: {latest_analysis_date}")

    # 2. 데이터 수집 (최신 날짜가 없으면 처음부터, 있으면 1페이지만)
    fetch_pages = 1 if latest_history_date else 15
    scraped_data = fetch_credit_balance_history(pages=fetch_pages)
    
    # 3. 새로운 데이터 필터링 및 동기화
    new_data = []
    if scraped_data:
        if latest_history_date:
            new_data = [item for item in scraped_data if item['date'] > latest_history_date]
        else:
            new_data = scraped_data

    if new_data:
        print(f"✨ {len(new_data)}개의 새로운 데이터가 발견되었습니다.")
        sync_to_supabase(new_data)
        # 데이터가 추가되었으므로 최신 날짜 다시 갱신
        latest_history_date = get_latest_date_from_db()
    else:
        print("✅ 히스토리는 이미 최신 상태입니다.")

    # 4. 분석 실행 여부 판단 (데이터 수집과 독립적으로 실행)
    if latest_history_date and (latest_history_date != latest_analysis_date):
        print(f"🚀 분석이 필요합니다. ({latest_analysis_date} -> {latest_history_date})")
        try:
            res = supabase.table("credit_balance_history").select("*").order("date", desc=False).execute()
            history_df = pd.DataFrame(res.data)
            
            if not history_df.empty:
                latest_record = history_df.iloc[-1].to_dict()
                analysis_res = analyze_credit_sentiment(history_df)
                
                if analysis_res:
                    update_analysis(analysis_res, latest_record)
                    print(f"✅ {latest_record['date']} 기준 분석 완료")
                    
                    # 푸시 알림 전송
                    try:
                        send_push_to_all(
                            title="🏦 신용융자 잔고 업데이트",
                            body=f"신규 데이터({latest_record['date']})가 수집되었습니다. 시장의 '빚투' 심리 분석을 확인하세요.",
                            url="/credit-balance"
                        )
                    except Exception as e:
                        print(f"Failed to send push: {e}")
        except Exception as e:
            print(f"❌ 분석 프로세스 중 에러: {e}")
    else:
        print("✅ 분석 결과가 이미 최신 데이터와 일치합니다.")

if __name__ == "__main__":
    main()
