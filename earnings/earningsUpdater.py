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
    과거 데이터 업데이트.
    1️⃣ revenue_actual이 NULL인 레코드만 업데이트 (매출값)
    2️⃣ 모든 과거 데이터에 대해 현재 주가 업데이트
    """
    
    if not supabase:
        print("❌ Supabase 설정 누락")
        return
    
    print("🔄 과거 실적 데이터 업데이트 시작...")
    
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
    
    # ==================== 2️⃣ 모든 과거 데이터의 현재 주가 업데이트 ====================
    print("💰 모든 과거 데이터의 현재 주가 업데이트 중...")
    price_update_count = 0
    
    for record in past_records:
        symbol = record['symbol']
        date_str = record['date']
        
        try:
            # 현재 주가가 없으면 조회
            if record.get('current_price') is None:
                try:
                    stock = yf.Ticker(symbol)
                    hist = stock.history(period='1d')
                    if not hist.empty:
                        current_price = float(hist['Close'].iloc[-1])
                        supabase.table("earnings_calendar").update({'current_price': current_price}).eq("symbol", symbol).eq("date", date_str).execute()
                        print(f"  ✅ {symbol} ({date_str}) 주가 추가: ${current_price:.2f}" if symbol not in ['KS', 'KQ'] else f"  ✅ {symbol} ({date_str}) 주가 추가: ₩{current_price:,.0f}")
                        price_update_count += 1
                except Exception as e:
                    pass
        except Exception as e:
            pass
    
    print(f"📊 총 {price_update_count}개 레코드에 주가 추가 완료")
    
    # ==================== 1️⃣ revenue_actual이 NULL인 레코드만 업데이트 (매출값) ====================
    # revenue_actual이 이미 있는 것들은 스킵
    needs_update = [r for r in past_records if r.get('revenue_actual') is None]
    print(f"⏳ 매출값 미보유 레코드: {len(needs_update)}개")
    
    revenue_update_count = 0
    
    for record in needs_update:
        symbol = record['symbol']
        country = record['country']
        date_str = record['date']
        earning_date = datetime.fromisoformat(date_str).date()
        
        try:
            # yfinance에서 현재 데이터 재조회
            stock = yf.Ticker(symbol)
            
            # quarterly_income_stmt에서 매출(Revenue) 조회
            try:
                income_stmt = stock.quarterly_income_stmt
                if income_stmt is not None and not income_stmt.empty:
                    latest_revenue = None
                    
                    # 발표 날짜 기준으로 해당 분기 찾기
                    # 발표는 보통 분기 종료 후 20-50일 후에 발생
                    if 'Total Revenue' in income_stmt.index:
                        for col_idx, col_date in enumerate(income_stmt.columns):
                            col_date_obj = col_date.date() if hasattr(col_date, 'date') else col_date
                            # 발표 날짜가 분기 종료 후 3개월 이내면 그 분기 데이터 사용
                            if col_date_obj < earning_date < col_date_obj + timedelta(days=120):
                                val = income_stmt.loc['Total Revenue'].iloc[col_idx]
                                if pd.notnull(val):
                                    latest_revenue = val
                                    break
                        
                        # 못 찾으면 최신 분기 사용
                        if latest_revenue is None:
                            latest_revenue = income_stmt.loc['Total Revenue'].iloc[0]
                    
                    if latest_revenue is not None and pd.notnull(latest_revenue):
                        # ✅ 매출값 업데이트
                        update_data = {
                            'revenue_actual': float(latest_revenue),
                            'revenue_actual_formatted': format_revenue(float(latest_revenue), country),
                            'updated_at': datetime.now().isoformat()
                        }
                        supabase.table("earnings_calendar").update(update_data).eq("symbol", symbol).eq("date", date_str).execute()
                        print(f"✅ {symbol} ({date_str}) 매출: {update_data['revenue_actual_formatted']}")
                        revenue_update_count += 1
                    else:
                        print(f"⏳ {symbol} ({date_str}) yfinance 아직 미반영 (재시도 필요)")
            except Exception as e:
                print(f"⚠️ {symbol} quarterly_income_stmt 조회 실패: {e}")
                continue
        
        except Exception as e:
            print(f"⚠️ {symbol} 처리 중 오류: {e}")
            continue
    
    print(f"📊 총 {revenue_update_count}개 레코드에 매출값 추가 완료")

if __name__ == "__main__":
    update_past_earnings()
