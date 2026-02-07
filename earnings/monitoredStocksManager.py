"""
S&P 100 / KOSPI Top 50 구성 변화를 추적하는 스크립트.

기능:
- 현재 S&P 100, KOSPI 50 리스트 조회
- DB의 monitored_stocks와 비교
- 편입(신규) / 편출(제거) 추적
- 편출된 종목은 soft delete (status='inactive')
"""

import os
import sys
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

def get_sp100_tickers():
    """미국 S&P 100 티커 리스트"""
    try:
        url = "https://en.wikipedia.org/wiki/S%26P_100"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers)
        tables = pd.read_html(res.text)
        for table in tables:
            if 'Symbol' in table.columns:
                symbols = [str(s).replace('.', '-') for s in table['Symbol']]
                return set(symbols)
        return set()
    except Exception as e:
        print(f"⚠️ S&P 100 수집 실패: {e}")
        return set()

def get_kospi_top_tickers(limit=50):
    """네이버 증시 코스피 Top 50 티커"""
    try:
        url = "https://finance.naver.com/sise/sise_market_sum.nhn?sosok=0&page=1"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(res.text, 'lxml')
        
        items = soup.select('a.tltle')
        symbols = []
        for item in items[:limit]:
            code = item['href'].split('=')[-1]
            symbols.append(f"{code}.KS")
        return set(symbols)
    except Exception as e:
        print(f"⚠️ KOSPI Top 50 수집 실패: {e}")
        return set()

def sync_monitored_stocks():
    """
    현재 인덱스와 DB의 monitored_stocks를 동기화
    """
    
    if not supabase:
        print("❌ Supabase 설정 누락")
        return
    
    print("🔄 모니터링 대상 종목 동기화 시작...")
    
    # 1️⃣ 현재 인덱스 구성 조회
    sp100_now = get_sp100_tickers()
    kospi50_now = get_kospi_top_tickers(50)
    
    print(f"📊 현재 S&P 100: {len(sp100_now)}개")
    print(f"📊 현재 KOSPI 50: {len(kospi50_now)}개")
    
    # 2️⃣ DB의 활성 종목 조회
    try:
        response = supabase.table("monitored_stocks").select("*").eq("status", "active").execute()
        db_active = {r['symbol']: r for r in response.data}
    except Exception as e:
        print(f"❌ DB 조회 실패: {e}")
        return
    
    db_symbols = set(db_active.keys())
    
    all_symbols_now = sp100_now | kospi50_now
    
    # 3️⃣ 편입(신규) 종목
    new_symbols = all_symbols_now - db_symbols
    
    if new_symbols:
        print(f"\n✨ 신규 편입 ({len(new_symbols)}개):")
        for symbol in new_symbols:
            country = "US" if '.KS' not in symbol else "KR"
            new_record = {
                'symbol': symbol,
                'company_name': symbol,  # 나중에 업데이트
                'country': country,
                'status': 'active',
                'added_at': datetime.now().isoformat()
            }
            try:
                supabase.table("monitored_stocks").insert(new_record).execute()
                print(f"  ✅ {symbol} 추가됨")
            except Exception as e:
                print(f"  ⚠️ {symbol} 추가 실패: {e}")
    
    # 4️⃣ 편출(제거) 종목
    removed_symbols = db_symbols - all_symbols_now
    
    if removed_symbols:
        print(f"\n🗑️ 편출 ({len(removed_symbols)}개):")
        for symbol in removed_symbols:
            try:
                supabase.table("monitored_stocks").update(
                    {'status': 'inactive', 'removed_at': datetime.now().isoformat()}
                ).eq("symbol", symbol).execute()
                print(f"  ✅ {symbol} 비활성화됨 (기존 데이터 유지)")
            except Exception as e:
                print(f"  ⚠️ {symbol} 비활성화 실패: {e}")
    
    if not new_symbols and not removed_symbols:
        print("\n✅ 구성 변화 없음")
    
    print("\n✅ 동기화 완료")

if __name__ == "__main__":
    sync_monitored_stocks()
