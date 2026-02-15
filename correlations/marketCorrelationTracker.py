import os
import sys
import pandas as pd
import yfinance as yf
import exchange_calendars as xcals
from datetime import datetime, timedelta
import pytz
from supabase import create_client, Client
from dotenv import load_dotenv
from revalidate import revalidate_path

# 상위 디렉토리 참조를 위해 sys.path 설정
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

# 환경 변수
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL or SUPABASE_KEY is missing.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def calculate_and_sync_history(days=60):
    """
    최근 N일간의 상관계수와 지수 데이터를 계산하여 DB에 저장
    """
    kst = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(kst)
    today = now_kst.date()
    yesterday = today - timedelta(days=1)
    
    # 1. 휴장일 체크 (엄격하게 양국 모두 개장한 경우에만 진행)
    krx_cal = xcals.get_calendar("XKRX")
    nys_cal = xcals.get_calendar("XNYS")

    is_kr_open = krx_cal.is_session(today)
    is_us_open = nys_cal.is_session(yesterday)

    if not is_kr_open or not is_us_open:
        print(f"⚠ 휴장일 알림: 오늘은 동기화를 진행하지 않습니다. (한국 개장: {is_kr_open}, 미국(전일) 개장: {is_us_open})")
        return

    print(f">>> 정상 영업일 확인됨. (KR: {today}, US: {yesterday})")

    # 20일 상관계수를 위해 약 100일 분량의 데이터 확보
    start_fetch = (today - timedelta(days=100)).strftime('%Y-%m-%d')
    end_fetch = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 데이터 수집 (안정성 및 변동률 계산을 위해 각각 다운로드)
    print(f">>> {start_fetch}부터 {end_fetch}까지의 데이터를 수집 중...")
    
    kospi_data = yf.download("^KS11", start=start_fetch, end=end_fetch, progress=False)
    sp500_data = yf.download("^GSPC", start=start_fetch, end=end_fetch, progress=False)
    
    if kospi_data.empty or sp500_data.empty:
        print("데이터 수집 실패: yfinance에서 데이터를 가져오지 못했습니다.")
        return

    # 종가 데이터 추출
    k_close = kospi_data['Close']
    s_close = sp500_data['Close']

    # 병합용 DataFrame 생성 (날짜 기준 맞춤)
    df = pd.DataFrame({
        'KOSPI': k_close.iloc[:, 0] if isinstance(k_close, pd.DataFrame) else k_close,
        'SP500': s_close.iloc[:, 0] if isinstance(s_close, pd.DataFrame) else s_close
    }).dropna()

    # 변동률 계산 (오늘 종가 vs 전 거래일 종가)
    df['KOSPI_Change'] = df['KOSPI'].pct_change() * 100
    df['SP500_Change'] = df['SP500'].pct_change() * 100

    # 수익률 계산 및 시차 보정 (미국 전일(T-1) -> 한국 오늘(T))
    # 미국 시장 수익률을 1거래일 뒤로 미뤄서 한국 오늘 날짜와 매칭
    df['SP500_Lagged_Return'] = df['SP500'].pct_change().shift(1)
    df['KOSPI_Return'] = df['KOSPI'].pct_change()
    
    # 20일 이동 상관계수 산출
    df['Correlation'] = df['KOSPI_Return'].rolling(window=20).corr(df['SP500_Lagged_Return'])
    
    # 계산 데이터가 있는 행만 필터링 (NaN 제거)
    final_df = df.dropna().tail(days)
    
    print(f">>> 총 {len(final_df)}건의 데이터를 DB에 동기화합니다...")
    
    for date, row in final_df.iterrows():
        date_str = date.strftime('%Y-%m-%d')
        payload = {
            "date": date_str,
            "correlation_value": round(float(row['Correlation']), 4),
            "kospi_value": round(float(row['KOSPI']), 2),
            "sp500_value": round(float(row['SP500']), 2),
            "kospi_change": round(float(row['KOSPI_Change']), 2),
            "sp500_change": round(float(row['SP500_Change']), 2),
            "type": "KOSPI_SP500_20D"
        }
        try:
            supabase.table("market_correlations").upsert(payload).execute()
        except Exception as e:
            print(f"Error on {date_str}: {e}")
    
    print(">>> 동기화 완료.")
    revalidate_path("/market-correlation")

def main():
    # 데일리 자동화용: 최근 5일치만 동기화 (주말/휴장일 고려)
    # 한 번씩 수동으로 더 많이 채우고 싶을 땐 숫자를 높이면 됩니다.
    calculate_and_sync_history(5)

if __name__ == "__main__":
    main()