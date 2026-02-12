import os
import sys
import pandas as pd
import exchange_calendars as xcals
from datetime import datetime, timedelta
import pytz
from supabase import create_client, Client
from google import genai
from dotenv import load_dotenv
import json

from news.push_notification import send_push_notification
import time

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

def notify_upcoming_holidays():
    """
    증시 휴장일 알림 시스템
    한국: 휴장 전날 밤 9시 알림
    미국: 휴장 당일 오전 9시 알림
    """
    if not supabase:
        return

    try:
        now_kst = datetime.now(pytz.timezone('Asia/Seoul'))
        today_str = now_kst.strftime('%Y-%m-%d')
        tomorrow_str = (now_kst + timedelta(days=1)).strftime('%Y-%m-%d')
        
        print(f"[{now_kst.strftime('%Y-%m-%d %H:%M:%S')}] Checking for holiday notifications...")

        # 1. 한국 휴장일 체크 (내일이 휴장일인 경우, 오늘 밤 9시에 알림)
        if now_kst.hour == 21:
            res = supabase.table("market_holidays").select("*").eq("date", tomorrow_str).eq("country", "KR").execute()
            if res.data:
                holiday = res.data[0]
                send_push_notification(
                    title="🇰🇷 내일은 국내 증시 휴장일입니다",
                    body=f"내일({tomorrow_str})은 {holiday['name_ko']}로 인해 한국 시장이 휴장합니다. 투자에 유의하세요.",
                    url="/market-holidays",
                    category="market_holidays"
                )
                print(f"KR Holiday Notification Sent: {holiday['name_ko']}")

        # 2. 미국 휴장일 체크 (오늘이 휴장일인 경우, 오늘 아침 9시에 알림)
        if now_kst.hour == 9:
            res = supabase.table("market_holidays").select("*").eq("date", today_str).eq("country", "US").execute()
            if res.data:
                holiday = res.data[0]
                send_push_notification(
                    title="🇺🇸 오늘은 미국 증시 휴장일입니다",
                    body=f"오늘({today_str})은 {holiday['name_ko']}로 인해 미국 시장이 휴장합니다. 서비스 이용에 참고하세요.",
                    url="/market-holidays",
                    category="market_holidays"
                )
                print(f"US Holiday Notification Sent: {holiday['name_ko']}")

    except Exception as e:
        print(f"Error in notify_upcoming_holidays: {e}")

def translate_holiday_names(holidays_list):
    """
    Gemini를 사용하여 휴장일 이름을 한국어로 번역합니다.
    """
    if not genai_client or not holidays_list:
        return {h: h for h in holidays_list}
    
    unique_names = list(set([h['name'] for h in holidays_list if h['name'] != "Market Holiday"]))
    if not unique_names:
        return {}

    try:
        prompt = f"""
        다음 주식 시장 휴장일(영문)을 한국인들이 이해하기 쉬운 공식 명칭으로 번역해줘.
        예: 'Thanksgiving Day' -> '추수감사절', 'Good Friday' -> '성금요일'
        반드시 JSON 형식으로 반환해: {{"영문명": "한국어명"}}
        
        {unique_names}
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
        print(f"⚠️ 휴장명 번역 실패: {e}")
        return {}

def is_market_dst(cal, dt_str):
    """지정한 날짜(YYYY-MM-DD)가 해당 거래소의 섬머타임(DST) 기간인지 확인합니다."""
    tz = cal.tz
    dt = datetime.strptime(dt_str, '%Y-%m-%d').replace(hour=12)
    
    # zoneinfo.ZoneInfo와 pytz 양쪽 모두 대응
    if hasattr(tz, 'localize'):
        localized_dt = tz.localize(dt)
    else:
        localized_dt = dt.replace(tzinfo=tz)
        
    dst_offset = localized_dt.dst()
    return dst_offset is not None and dst_offset.total_seconds() > 0

def fetch_and_save_holidays(year):
    if not supabase:
        print("❌ Supabase 클라이언트가 초기화되지 않았습니다.")
        return

    # 거래소 매핑
    exchanges = {
        "KR": "XKRX",
        "US": "XNYS"
    }

    start_date = pd.Timestamp(f"{year}-01-01")
    end_date = pd.Timestamp(f"{year}-12-31")

    all_holidays = []

    for country, exchange_code in exchanges.items():
        print(f"🔍 Fetching holidays for {country} ({exchange_code}) for {year}...")
        cal = xcals.get_calendar(exchange_code)
        
        # 1. 휴장일 (Non-trading days)
        all_days = pd.date_range(start_date, end_date)
        sessions = cal.sessions_in_range(start_date, end_date)
        non_sessions = all_days.difference(sessions)
        
        # 주말 제외 (토=5, 일=6)
        holidays_only = [d for d in non_sessions if d.dayofweek < 5]
        
        # 2. 휴장 명칭 찾기 (regular_holidays 사용)
        # exchange_calendars 내부 mapping을 활용하거나, 
        # 간단하게 'Market Holiday'로 넣고 나중에 Gemini가 한 번에 처리하도록 함.
        # adhoc_holidays 등도 포함
        
        for h_date in holidays_only:
            date_str = h_date.strftime('%Y-%m-%d')
            # 캘린더에서 해당 날짜의 명칭을 가져오려고 시도 (v4+ 기준)
            # 명칭을 가져오기 어려울 경우 날짜 정보를 보고 Gemini에게 추측 시킬 수도 있음
            # 여기서는 기본 'Market Holiday'로 설정 후 Gemini에게 날짜와 함께 넘김
            all_holidays.append({
                "date": date_str,
                "country": country,
                "name": "Market Holiday", # 임시
                "type": "holiday",
                "is_dst": is_market_dst(cal, date_str),
                "close_time": None
            })
            
        # 3. 조기 종료 (Half-day)
        if hasattr(cal, 'special_closes'):
            # special_closes는 [(time, HolidayCalendar), ...] 형태임
            for close_time, holiday_calendar in cal.special_closes:
                # 해당 연도 범위 내의 날짜들만 추출
                special_dates = holiday_calendar.holidays(start_date, end_date)
                for d in special_dates:
                    date_str = d.strftime('%Y-%m-%d')
                    # 중복 방지 (이미 휴무일인 경우 제외)
                    if not any(h['date'] == date_str and h['country'] == country for h in all_holidays):
                        all_holidays.append({
                            "date": date_str,
                            "country": country,
                            "name": f"Early Close ({close_time})",
                            "type": "half_day",
                            "is_dst": is_market_dst(cal, date_str),
                            "close_time": close_time.strftime('%H:%M:%S')
                        })

    # Gemini 번역 처리 (날짜 정보를 포함해 다시 한 번 정제)
    print("🤖 Translating holiday names using Gemini...")
    try:
        # 날짜와 국가 정보를 포함해 정확한 명칭 요청
        h_info = [{"date": h['date'], "country": h['country'], "type": h['type']} for h in all_holidays]
        prompt = f"""
        다음 주식 시장 휴장/조기종료 리스트를 보고 각각의 공식 한국어 명칭(예: 추석, 크리스마스, 대통령의 날 등)을 찾아서 JSON 배열로 반환해줘.
        'half_day'인 경우 '조기 종료(명칭)' 형태로 해줘.
        반드시 [{{ "date": "...", "country": "...", "name_ko": "..." }}] 형식의 JSON 배열로 반환해.
        
        리스트: {h_info}
        """
        response = genai_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        translated_data = json.loads(response.text)
        
        # 번역 내용 매핑
        translation_map = {(t['date'], t['country']): t['name_ko'] for t in translated_data}
        for h in all_holidays:
            h['name_ko'] = translation_map.get((h['date'], h['country']), h['name'])
            h['updated_at'] = datetime.now().isoformat()
            # 원본 name은 'Market Holiday' 대신 name_ko가 없을 때의 대비책으로만 유지

    except Exception as e:
        print(f"⚠️ 번역 프로세스 실패: {e}")
        for h in all_holidays:
            h['name_ko'] = h['name']
            h['updated_at'] = datetime.now().isoformat()

    # Supabase UPSERT
    if all_holidays:
        try:
            res = supabase.table("market_holidays").upsert(all_holidays, on_conflict="date,country").execute()
            print(f"✅ Successfully updated {len(all_holidays)} records in Supabase.")
        except Exception as e:
            print(f"❌ Error during Supabase upsert: {e}")

if __name__ == "__main__":
    print("🎬 Holiday Tracker & Notifier is running...")
    
    # 처음 실행 시 1회 데이터 수집
    for year in [2025, 2026]:
        print(f"\n--- Initial Fetching for Year: {year} ---")
        fetch_and_save_holidays(year)
    
    while True:
        try:
            # 알림 체크
            notify_upcoming_holidays()
            
            # 매일 정오에 한 번씩 데이터도 새로 갱신 (선택 사항)
            now = datetime.now(pytz.timezone('Asia/Seoul'))
            if now.hour == 12:
                print("\n--- Daily Update: Fetching Holidays ---")
                fetch_and_save_holidays(now.year)
                fetch_and_save_holidays(now.year + 1)
            
            # 1시간 대기 (알림 체크 누락 방지 및 리소스 절약)
            time.sleep(3600) 
            
        except KeyboardInterrupt:
            print("Tracker stopped by user.")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(600)
