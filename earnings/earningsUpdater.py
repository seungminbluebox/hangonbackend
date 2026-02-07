"""
실적 발표 후 실제값(eps_actual, revenue_actual)을 업데이트하는 스크립트.

실행 주기: 일 1회 (저녁 또는 새벽)
목적: 과거(발표 완료된) 실적 데이터만 스캔하여 누락된 실제값 채우기
"""

import os
import sys
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import GEMINI_MODEL_NAME

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

def format_revenue(value, country):
    """매출액 단위 변환 로직"""
    if value is None or value == 0 or pd.isna(value):
        return "N/A"
    
    if country == 'US':
        if value >= 1e12:
            return f"{value / 1e12:.1f}조 달러"
        elif value >= 1e8:
            return f"{value / 1e8:.1f}억 달러"
        else:
            return f"${value:,.0f}"
    else:
        if value >= 1e12:
            return f"{value / 1e12:.1f}조 원"
        elif value >= 1e8:
            return f"{value / 1e8:.1f}억 원"
        else:
            return f"{value:,.0f}원"

def update_past_earnings():
    """
    과거 데이터만 업데이트.
    ⚠️ 매출값(revenue_actual, revenue_actual_formatted)만 채워넣음
    기존 데이터는 절대 덮어쓰지 않음 (eps_estimate, eps_actual 등)
    
    - earnings_calendar에서 date < today인 레코드 조회
    - revenue_actual이 NULL인 레코드만 업데이트 시도
    - 다른 필드는 건드리지 않음
    """
    
    if not supabase:
        print("❌ Supabase 설정 누락")
        return
    
    print("🔄 과거 실적 데이터(매출값) 업데이트 시작...")
    
    today = datetime.now().date()
    
    # 1️⃣ 과거 데이터 조회 (발표 예정일이 오늘 미만 = 이미 발표됨)
    try:
        response = supabase.table("earnings_calendar").select("*").execute()
        all_records = response.data
    except Exception as e:
        print(f"❌ DB 조회 실패: {e}")
        return
    
    # 과거 레코드 필터링 (date < today)
    past_records = [r for r in all_records if datetime.fromisoformat(r['date']).date() < today]
    
    print(f"📋 과거 레코드: {len(past_records)}개")
    
    # revenue_actual이 이미 있는 것들은 스킵
    needs_update = [r for r in past_records if r.get('revenue_actual') is None]
    print(f"⏳ 매출값 미보유 레코드: {len(needs_update)}개")
    
    update_count = 0
    
    for record in needs_update:
        symbol = record['symbol']
        country = record['country']
        date_str = record['date']
        
        try:
            # yfinance에서 현재 데이터 재조회
            stock = yf.Ticker(symbol)
            
            # quarterly_income_stmt에서 매출(Revenue) 조회 (가장 최근 분기)
            try:
                income_stmt = stock.quarterly_income_stmt
                if income_stmt is not None and not income_stmt.empty:
                    # 'Total Revenue' 행 찾기
                    revenue_row = None
                    for idx in income_stmt.index:
                        if 'Total Revenue' in str(idx) or 'Revenue' in str(idx):
                            revenue_row = income_stmt.loc[idx]
                            break
                    
                    if revenue_row is not None:
                        # 가장 최근(첫 번째 컬럼)의 매출 데이터
                        latest_revenue = revenue_row.iloc[0]
                        
                        if pd.notnull(latest_revenue):
                            # ✅ 매출값만 업데이트 (다른 필드는 건드리지 않음)
                            update_data = {
                                'revenue_actual': float(latest_revenue),
                                'revenue_actual_formatted': format_revenue(float(latest_revenue), country),
                                'updated_at': datetime.now().isoformat()
                            }
                            supabase.table("earnings_calendar").update(update_data).eq("symbol", symbol).eq("date", date_str).execute()
                            print(f"✅ {symbol} ({date_str}) 매출 추가: {update_data['revenue_actual_formatted']}")
                            update_count += 1
                        else:
                            print(f"⏳ {symbol} ({date_str}) yfinance 아직 미반영 (재시도 필요)")
            except Exception as e:
                print(f"⚠️ {symbol} quarterly_income_stmt 조회 실패: {e}")
                continue
        
        except Exception as e:
            print(f"⚠️ {symbol} 처리 중 오류: {e}")
            continue
    
    print(f"📊 총 {update_count}개 레코드에 매출값 추가 완료")

if __name__ == "__main__":
    update_past_earnings()
