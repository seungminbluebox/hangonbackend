import os
import json
import requests
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_market_data():
    symbols = [
        {"name": "KOSPI", "symbol": "^KS11"},
        {"name": "KOSDAQ", "symbol": "^KQ11"},
        {"name": "S&P 500", "symbol": "^GSPC"},
        {"name": "NASDAQ", "symbol": "^IXIC"},
        {"name": "다우존스", "symbol": "^DJI"},
        {"name": "원/달러 환율", "symbol": "USDKRW=X"},
        {"name": "비트코인", "symbol": "BTC-USD"},
        {"name": "금 가격(온스)", "symbol": "GC=F"},
        {"name": "WTI 원유", "symbol": "CL=F"},
    ]

    results = []
    exchange_rate = None

    # 환율 먼저 가져오기 (원화 환산을 위해)
    for s in symbols:
        symbol = s["symbol"]
        name = s["name"]
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=30m&range=1d"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers)
            data = response.json()

            result = data["chart"]["result"][0]
            meta = result["meta"]
            quote = result["indicators"]["quote"][0]
            close_prices = [p for p in quote["close"] if p is not None]

            current_price = meta["regularMarketPrice"]
            previous_close = meta["previousClose"]
            change = current_price - previous_close
            change_percent = (change / previous_close) * 100

            item = {
                "name": name,
                "symbol": symbol,
                "current_numeric": current_price,
                "value": "{:,.2f}".format(current_price),
                "change": "{:,.2f}".format(abs(change)),
                "change_percent": "{}{:,.2f}%".format("+" if change > 0 else "", change_percent),
                "is_up": change > 0,
                "is_down": change < 0,
                "history": [{"value": p} for p in close_prices]
            }
            
            if symbol == "USDKRW=X":
                exchange_rate = current_price
            
            results.append(item)
            print(f"Fetched {name}")
        except Exception as e:
            print(f"Error fetching {name}: {e}")

    # 비트코인 원화 환산 및 DB 저장
    for item in results:
        krw_value = None
        if item["symbol"] == "BTC-USD" and exchange_rate:
            converted = item["current_numeric"] * exchange_rate
            krw_value = "₩{:,.0f}".format(converted)
        
        # DB 업서트 (Upsert)
        data_to_save = {
            "name": item["name"],
            "symbol": item["symbol"],
            "value": item["value"],
            "change": item["change"],
            "change_percent": item["change_percent"],
            "is_up": item["is_up"],
            "is_down": item["is_down"],
            "history": item["history"],
            "krw_value": krw_value,
            "updated_at": datetime.now().isoformat()
        }

        try:
            supabase.table("market_data").upsert(
                data_to_save, on_conflict="symbol"
            ).execute()
        except Exception as e:
            print(f"Error saving {item['name']} to DB: {e}")

if __name__ == "__main__":
    print("Starting Market Data Update...")
    fetch_market_data()
    print("Market Data Update Finished.")
