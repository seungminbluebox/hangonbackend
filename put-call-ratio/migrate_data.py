import os
import sys
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv

# 상위 디렉토리의 config 등을 참조하기 위함
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def migrate():
    csv_path = os.path.join(os.path.dirname(__file__), 'cboe_history.csv')
    print(f"Loading CSV data from: {csv_path}")
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}")
        return

    df = pd.read_csv(csv_path)
    # 컬럼명을 모두 소문자로 변환 (Supabase 테이블과 매칭)
    df.columns = [col.lower() for col in df.columns]
    
    # Date를 기준으로 정렬
    df = df.sort_values('date')
    
    data = df.to_dict(orient='records')
    
    print(f"Migrating {len(data)} records to 'pcr_history'...")
    
    try:
        # pcr_history 테이블이 있다고 가정 (날짜가 PK여야 함)
        # 만약 테이블이 없으면 에러가 날 것이므로 사용자에게 안내
        res = supabase.table("pcr_history").upsert(data).execute()
        print("Successfully migrated PCR history!")
    except Exception as e:
        print(f"Error during migration: {e}")
        print("\n[SQL] 아래 명령어를 Supabase SQL Editor에서 실행하여 테이블을 먼저 생성해주세요:")
        print("""
        CREATE TABLE pcr_history (
            date DATE PRIMARY KEY,
            total FLOAT,
            index FLOAT,
            equity FLOAT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """)

if __name__ == "__main__":
    migrate()
