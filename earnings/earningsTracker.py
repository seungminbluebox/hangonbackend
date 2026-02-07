import os
import sys
import json
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from supabase import create_client, Client
from google import genai
from dotenv import load_dotenv

# 상위 디렉토리 참조
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import GEMINI_MODEL_NAME

load_dotenv()

# 환경 변수
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 환경 변수(SUPABASE_URL, SUPABASE_KEY)가 설정되지 않았습니다.")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Gemini 클라이언트 초기화
genai_client = genai.Client(api_key=GOOGLE_API_KEY) if GOOGLE_API_KEY else None

def translate_company_names(en_names):
    """
    Gemini를 사용하여 기업명을 한국어로 자연스럽게 번역합니다.
    """
    if not genai_client or not en_names:
        return {name: name for name in en_names}
    
    try:
        # 번역 효율을 위해 리스트를 하나의 문자열로 합침
        prompt = f"""
        다음 기업 리스트를 한국인에게 친숙한 공식 한국어 기업명으로 번역해줘. 
        반드시 JSON 형식으로 반환해: {{"원래이름": "번역된이름"}}
        
        {en_names}
        """
        response = genai_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"⚠️ 기업명 번역 실패: {e}")
        return {name: name for name in en_names}

def get_sp100_tickers():
    """미국 시총 상위 100대 기업 리스트와 이름을 Wikipedia에서 가져옵니다."""
    try:
        url = "https://en.wikipedia.org/wiki/S%26P_100"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers)
        tables = pd.read_html(res.text)
        for table in tables:
            if 'Symbol' in table.columns and 'Name' in table.columns:
                # {Symbol: Name} 딕셔너리 생성
                mapping = {}
                for _, row in table.iterrows():
                    symbol = str(row['Symbol']).replace('.', '-')
                    mapping[symbol] = row['Name']
                return mapping
        return {}
    except Exception as e:
        print(f"⚠️ S&P 100 티커 수집 실패: {e}")
        return []

def get_kospi_top_tickers(limit=50):
    """네이버 증시에서 코스피 시총 상위 종목명과 코드를 가져옵니다."""
    try:
        url = "https://finance.naver.com/sise/sise_market_sum.nhn?sosok=0&page=1"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(res.text, 'lxml')
        
        items = soup.select('a.tltle')
        mapping = {}
        for item in items[:limit]:
            code = item['href'].split('=')[-1]
            name = item.text.strip()
            mapping[f"{code}.KS"] = name
        return mapping
    except Exception as e:
        print(f"⚠️ KOSPI 티커 수집 실패: {e}")
        return {}

def resolve_ticker_list():
    """관심 종목 리스트와 캐시된 한글명을 결정합니다."""
    # 1. Supabase 'monitored_stocks' 테이블 활용
    if supabase:
        try:
            res = supabase.table("monitored_stocks").select("symbol, name").eq("is_active", True).execute()
            if res.data and len(res.data) > 0:
                print(f"✅ Supabase에서 {len(res.data)}개의 종목을 가져왔습니다.")
                mapping = {item['symbol']: item.get('name') for item in res.data}
                return list(mapping.keys()), mapping
        except Exception:
            pass

    # 2. 동적 수집 (US Top 100 + KR Top 50)
    print("🌐 실시간 시장 데이터를 기반으로 우량주 리스트를 구성합니다...")
    us_mapping = get_sp100_tickers()
    kr_mapping = get_kospi_top_tickers(50)
    
    combined_mapping = {**us_mapping, **kr_mapping}
    tickers = list(combined_mapping.keys())
    
    if not tickers:
        fallback = ["AAPL", "MSFT", "NVDA", "005930.KS", "000660.KS"]
        return fallback, {t: t for t in fallback}
        
    return tickers, combined_mapping

def format_revenue(value, country):
    """매출액 단위 변환 로직"""
    # NaN, None, 0 모두 처리
    if value is None or value == 0 or pd.isna(value):
        return "N/A"
    
    if country == 'US':
        # 미국 달러를 한국식 읽기 단위(조, 억)로 변환하여 직관성 높임
        if value >= 1e12:
            return f"{value / 1e12:.1f}조 달러"
        elif value >= 1e8:
            # $1B(10억 달러) 이상 또는 $100M(1억 달러) 이상 처리
            return f"{value / 1e8:.1f}억 달러"
        else:
            return f"${value:,.0f}"
    else:
        # 한국 원화 단위
        if value >= 1e12:
            return f"{value / 1e12:.1f}조 원"
        elif value >= 1e8:
            return f"{value / 1e8:.1f}억 원"
        else:
            return f"{value:,.0f}원"

def fetch_earnings_data(tickers, name_mapping, days_past=14, days_future=120):
    """
    미래 실적 데이터를 수집합니다 (earningsTracker 담당).
    과거 데이터 업데이트는 earningsUpdater.py가 별도로 처리합니다.
    
    Args:
        days_past: 과거 며칠까지 포함할 것인가 (기본 14일)
        days_future: 미래 며칠까지 조회할 것인가 (기본 120일)
    
    로직:
    - date > today인 미래 데이터만 수집 (새로운 어닝 일정)
    - date <= today인 과거 데이터는 이미 DB에 있으므로 스킵
    """
    print(f"🚀 {len(tickers)}개 종목에 대한 미래 실적 데이터 수집 시작...")
    
    us_tickers = [t for t in tickers if '.KS' not in t and '.KQ' not in t]
    us_en_names = [name_mapping.get(t, t) for t in us_tickers]
    
    print("🧠 Gemini를 사용하여 미국 기업명을 한글로 변환 중...")
    translated_names = translate_company_names(us_en_names)
    
    results = []
    for symbol in tickers:
        try:
            print(f"🔍 {symbol} 조회 중...")
            stock = yf.Ticker(symbol)
            
            # 1. EPS 데이터 수집 (과거/미래 모두)
            df = stock.earnings_dates
            if df is None or df.empty:
                print(f"⚠️ {symbol}에 실적 데이터가 없습니다.")
                continue
            
            # 2. 미래 예상치 소스: calendar
            cal = stock.calendar
            cal_rev_est = 0
            if cal is not None and isinstance(cal, dict):
                cal_rev_est = cal.get('Revenue Average', 0)
            
            # 3. 과거 실제 매출 소스: quarterly_income_stmt
            q_fin = stock.quarterly_income_stmt
            
            # 기업 정보
            country = 'KR' if '.KS' in symbol or '.KQ' in symbol else 'US'
            company_name = name_mapping.get(symbol, symbol) if country == 'KR' else translated_names.get(name_mapping.get(symbol, symbol), name_mapping.get(symbol, symbol))
            
            # 로고 URL 추출
            info = stock.info
            website = info.get('website')
            logo_url = None
            logodev_key = os.getenv("LOGODEV_PUBLISHABLE_KEY")
            if website:
                domain = website.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
                if logodev_key:
                    logo_url = f"https://img.logo.dev/{domain}?token={logodev_key}"
                else:
                    logo_url = f"https://img.logo.dev/{domain}"
            if not logo_url:
                logo_url = f"https://financialmodelingprep.com/image-stock/{symbol.split('.')[0]}.png"

            # 2026년 이후 데이터만 필터링
            df_filtered = df[df.index.year >= 2026].head(8)
            
            for timestamp, row in df_filtered.iterrows():
                ts_naive = timestamp.replace(tzinfo=None)
                date_key = ts_naive.strftime('%Y-%m-%d')
                
                eps_est = row.get('EPS Estimate', 0)
                
                is_past = ts_naive.date() < datetime.now().date()
                
                # ⚠️ earningsTracker는 미래 데이터만 수집
                # 과거 데이터 업데이트는 earningsUpdater.py가 담당
                if is_past:
                    continue
                
                # === 미래 (발표 예정 실적) ===
                # EPS: earnings_dates의 예상치
                # 매출: calendar의 예상치
                
                results.append({
                    'symbol': symbol,
                    'company_name': company_name,
                    'logo_url': logo_url,
                    'date': date_key,
                    'country': country,
                    'eps_estimate': float(eps_est) if pd.notnull(eps_est) else 0,
                    'eps_actual': None,
                    'revenue_estimate': float(cal_rev_est) if cal_rev_est > 0 else 0,
                    'revenue_estimate_formatted': format_revenue(cal_rev_est, country),
                    'revenue_actual': None,
                    'revenue_actual_formatted': "N/A",
                    'updated_at': datetime.now().isoformat()
                })
            
            print(f"✅ {symbol} ({company_name}) 데이터 갱신 완료")
            
        except Exception as e:
            print(f"❌ {symbol} 처리 중 에러: {e}")
            continue
            
    return results

def sync_to_supabase(data_list):
    """
    수집된 미래 데이터를 Supabase에 저장합니다.
    
    중요: 신규 레코드는 insert, 기존 레코드는 update로 처리
    → 기존의 revenue_actual 값을 절대 덮어쓰지 않음
    """
    if not data_list or supabase is None:
        print("ℹ️ 저장할 데이터가 없거나 Supabase 설정이 되어있지 않습니다.")
        return

    print(f"📤 {len(data_list)}개의 데이터를 Supabase 'earnings_calendar' 테이블에 저장 중...")
    
    insert_count = 0
    update_count = 0
    
    for record in data_list:
        try:
            symbol = record['symbol']
            date = record['date']
            
            # 1️⃣ 기존 레코드 확인
            existing = supabase.table("earnings_calendar").select("*").eq("symbol", symbol).eq("date", date).execute()
            
            if existing.data and len(existing.data) > 0:
                # 2️⃣ 기존 레코드가 있으면 → 미래 데이터만 업데이트 (revenue_actual 보존!)
                existing_record = existing.data[0]
                
                update_payload = {
                    'company_name': record['company_name'],
                    'logo_url': record['logo_url'],
                    'country': record['country'],
                    'eps_estimate': record['eps_estimate'],
                    'revenue_estimate': record['revenue_estimate'],
                    'revenue_estimate_formatted': record['revenue_estimate_formatted'],
                    'updated_at': record['updated_at']
                    # ⚠️ revenue_actual, revenue_actual_formatted는 절대 포함하지 않음!
                    # 기존 값을 보존하려면 빈 필드만 보낸다
                }
                
                supabase.table("earnings_calendar").update(update_payload).eq("symbol", symbol).eq("date", date).execute()
                print(f"  🔄 {symbol} ({date}) 업데이트 (기존 매출값 보존)")
                update_count += 1
            else:
                # 3️⃣ 신규 레코드 → insert
                supabase.table("earnings_calendar").insert(record).execute()
                print(f"  ✨ {symbol} ({date}) 신규 추가")
                insert_count += 1
        
        except Exception as e:
            print(f"  ❌ {record['symbol']} ({record['date']}) 저장 실패: {e}")
            continue
    
    print(f"✅ 저장 완료 (신규: {insert_count}, 업데이트: {update_count})")

if __name__ == "__main__":
    ticker_list, name_mapping = resolve_ticker_list()
    earnings_data = fetch_earnings_data(ticker_list, name_mapping)
    sync_to_supabase(earnings_data)
