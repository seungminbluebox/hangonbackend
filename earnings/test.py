import yfinance as yf
import pandas as pd
from datetime import datetime
import os

def format_revenue(value, country='US'):
    if value is None or value == 0 or pd.isnull(value):
        return "N/A"
    if country == 'US':
        if value >= 1e12: return f"{value / 1e12:.1f}조 달러"
        elif value >= 1e8: return f"{value / 1e8:.1f}억 달러"
        else: return f"${value:,.0f}"
    else:
        if value >= 1e12: return f"{value / 1e12:.1f}조 원"
        elif value >= 1e8: return f"{value / 1e8:.1f}억 원"
        else: return f"{value:,.0f}원"

def test_single_ticker(symbol):
    print(f"--- Testing {symbol} ---")
    stock = yf.Ticker(symbol)
    
    # 1. 실적 날짜 및 EPS 데이터
    df = stock.earnings_dates
    if df is None or df.empty:
        print("No earnings dates found.")
        return
    else:
        print(f"Earnings Dates Columns: {list(df.columns)}")
        # 과거 데이터 샘플 출력
        past_sample = df[df.index.date < datetime.now().date()].head(2)
        print("Past Earnings Dates Sample:")
        print(past_sample)

    # 2. 재무제표 (실제 매출 소스 1)
    q_fin = stock.quarterly_income_stmt
    
    # 3. 보조 실적 데이터 (실제 매출 소스 2 - 발표 직후 가장 빠름)
    # yfinance 패키지 내부의 새 경로 또는 earnings_history 시도
    q_earnings = pd.DataFrame()
    try:
        q_earnings = stock.earnings_history
        if q_earnings is not None and not q_earnings.empty:
            print(f"Earnings History Columns: {list(q_earnings.columns)}")
            print(f"Earnings History Index Range: {q_earnings.index.min()} to {q_earnings.index.max()}")
    except Exception as e: 
        print(f"Earnings History load failed: {e}")

    # 4. 캘린더 (미래 예상치 소스)
    cal = stock.calendar
    cal_rev_est = 0
    if cal is not None:
        try:
            if isinstance(cal, pd.DataFrame):
                cal_rev_est = cal.loc['Revenue Average'].iloc[0] if 'Revenue Average' in cal.index else 0
            else:
                cal_rev_est = cal.get('Revenue Average', 0)
        except: pass
    
    # 5. [추가] 실적 트렌드 (과거/미래 예상 매출의 보조 소스)
    e_trend = pd.DataFrame()
    try:
        e_trend = stock.earnings_trend
        if e_trend is not None and not e_trend.empty:
            print("Earnings Trend data found.")
    except: pass

    # 2026년 이후 데이터 필터링
    df_filtered = df[df.index.year >= 2026].head(5)
    
    for timestamp, row in df_filtered.iterrows():
        ts_naive = timestamp.replace(tzinfo=None)
        date_key = ts_naive.strftime('%Y-%m-%d')
        print(f"\n[날짜: {date_key}]")
        
        eps_est = row.get('EPS Estimate', 0)
        eps_act = row.get('Reported EPS')
        rev_est = row.get('Revenue Estimate', 0)
        rev_act = None
        
        is_past = ts_naive.date() < datetime.now().date()
        
        if is_past:
            # --- 실적 발표가 완료된 "과거" ---
            
            # 예상 매출 보완 (earnings_trend 활용)
            if (rev_est is None or rev_est == 0) and e_trend is not None and not e_trend.empty:
                try:
                    # '0y' (현재 분기/가장 최근), '-1y' (과거) 등에서 목표 날짜와 비슷한 항목 찾기
                    # yfinance의 earnings_trend는 보통 [0y, +1y, -1y, q0, q+1] 등으로 구성됨
                    for col in e_trend.columns:
                        period_data = e_trend[col]
                        # 기간(EndDate)이 실적 발표일(ts_naive)의 분기말과 일치하는지 확인
                        period_end = pd.to_datetime(period_data.get('endDate')).replace(tzinfo=None)
                        if (ts_naive - period_end).days > 0 and (ts_naive - period_end).days < 100:
                            rev_est = period_data.get('revenueEstimate', {}).get('avg', 0)
                            if rev_est > 0:
                                print(f"  -> 소스 C(Earnings Trend)에서 과거 예상 매출 수집 성공")
                                break
                except: pass

            # 소스 A: earnings_history (가장 정확하고 빠름)
            if q_earnings is not None and not q_earnings.empty:
                # 인덱스를 naive datetime으로 변환
                q_hist = q_earnings.copy()
                q_hist.index = pd.to_datetime(q_hist.index).tz_localize(None)
                
                # 날짜 오차(±1일)를 고려하여 가장 가까운 실적 기록 찾기
                # (After Hours 발표 시 날짜가 하루 차이날 수 있음)
                diffs = abs((q_hist.index - ts_naive).days)
                best_idx_position = diffs.argmin()
                best_idx = q_hist.index[best_idx_position]
                
                if diffs[best_idx_position] <= 1: # 1일 이내 오차만 허용
                    match_row = q_hist.loc[best_idx]
                    
                    # EPS 추집
                    if 'epsEstimate' in match_row: eps_est = match_row['epsEstimate']
                    if 'epsActual' in match_row: eps_act = match_row['epsActual']
                    
                    # 매출액 수집
                    if 'revenueEstimate' in match_row: rev_est = match_row['revenueEstimate']
                    if 'revenueActual' in match_row: rev_act = match_row['revenueActual']
                    
                    print(f"  -> 소스 A(Earnings History) 매칭 성공 (날짜 오차: {diffs[best_idx]}일)")

            # 소스 B: quarterly_income_stmt (소스 A 실패시 보조)
            if (rev_act is None or pd.isnull(rev_act)) and q_fin is not None and not q_fin.empty:
                best_match = None
                min_diff = 999
                for col_date in q_fin.columns:
                    diff = (ts_naive - col_date.replace(tzinfo=None)).days
                    if 0 < diff < 100:
                        if diff < min_diff:
                            min_diff = diff
                            best_match = col_date
                
                if best_match:
                    label = next((idx for idx in q_fin.index if str(idx).replace(" ","").lower() == "totalrevenue"), None)
                    if label:
                        rev_act = q_fin.loc[label, best_match]
                        print(f"  -> 소스 B(재무제표)에서 실제 매출 수집 성공")
        else:
            # --- 실적 발표 예정인 "미래" ---
            if pd.isnull(rev_est) or rev_est == 0:
                rev_est = cal_rev_est
                print(f"  -> 미래 예상 매출 수집 (Calendar): {rev_est}")

        # 결과 출력
        print(f"  - EPS: [예상] {eps_est} | [실제] {eps_act}")
        print(f"  - 매출: [예상] {format_revenue(rev_est)} | [실제] {format_revenue(rev_act)}")

if __name__ == "__main__":
    test_single_ticker("NFLX") # 넷플릭스로 테스트

