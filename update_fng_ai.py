import os
import json
import fear_and_greed
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_fear_greed_index():
    try:
        index = fear_and_greed.get()
        return {
            "value": round(index.value, 1),
            "description": index.description,
            "last_update": index.last_update.isoformat()
        }
    except Exception as e:
        print(f"Error fetching Fear & Greed Index: {e}")
        return None

def analyze_sentiment(fng_data):
    print("Analyzing market sentiment with AI...")
    prompt = f"""
    당신은 글로벌 금융 시장 분석 전문가입니다. 
    현재 CNN Fear & Greed Index(공포와 탐욕 지수) 정보를 바탕으로 시장 상황을 분석해 주세요.

    [지수 정보]
    - 지수 값: {fng_data['value']} (0: 극도의 공포, 100: 극도의 탐욕)
    - 상태: {fng_data['description']}

    [요청 사항]
    1. 현재 시장의 심리 상태를 아주 핵심만 짚어서 아주 쉽게 설명해 주세요. (금융 지식이 없는 사람도 이해할 수 있게)
    2. 분석(analysis) 내용은 긴 줄글이 아닌, 가독성이 좋은 3~4개의 짧은 문장 또는 불렛 포인트 형식으로 작성해 주세요.
    3. 전문 용어보다는 '비유'나 '일상적인 단어'를 사용해 주세요.
    4. 투자자가 지금 당장 가져야 할 마음가짐을 조언(advice)에 담아주세요.
    5. 전체적으로 "오늘 시장 분위기는 이렇습니다"라고 가볍게 브리핑하는 톤앤매너를 유지해 주세요.

    [JSON 형식]
    {{
        "title": "오늘의 시장 분위기 (한 줄 요약)",
        "analysis": "핵심 요약 내용 (문장별로 줄바꿈 적용)",
        "advice": ["조언1", "조언2", "조언3"]
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        res_data = json.loads(response.text)
        # 만약 결과가 리스트 형태로 왔다면 첫 번째 요소를 사용
        if isinstance(res_data, list):
            return res_data[0]
        return res_data
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        return {
            "title": "분석을 불러올 수 없습니다.",
            "analysis": "현재 AI 분석 기능에 일시적인 문제가 발생했습니다.",
            "advice": ["시장의 기본 지표를 참고해 주세요."]
        }

def update_db(fng_data, ai_analysis):
    print("Updating Supabase fear_greed table...")
    data = {
        "value": fng_data['value'],
        "description": fng_data['description'],
        "title": ai_analysis['title'],
        "analysis": ai_analysis['analysis'],
        "advice": ai_analysis['advice'],
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        # 'fear_greed' 테이블에 저장 (단일 레코드만 유지하거나 날짜별로 저장 가능)
        # 여기서는 가장 최근 상태 하나만 유지하도록 upsert (id=1 고정)
        data['id'] = 1
        result = supabase.table("fear_greed").upsert(data).execute()
        print("Successfully updated database!")
        return result
    except Exception as e:
        print(f"Error updating Supabase: {e}")
        return None

def main():
    fng_data = get_fear_greed_index()
    if not fng_data:
        print("Failed to get index data. Exiting.")
        return
    
    ai_analysis = analyze_sentiment(fng_data)
    update_db(fng_data, ai_analysis)

if __name__ == "__main__":
    main()
