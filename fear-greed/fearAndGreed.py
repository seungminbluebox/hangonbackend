import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
import fear_and_greed
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
from config import GEMINI_MODEL_NAME
from news.push_notification import send_push_to_all

load_dotenv()

# 환경 변수 설정
GOOGLE_API_KEY =  os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MODEL_NAME = GEMINI_MODEL_NAME

genai.configure(api_key=GOOGLE_API_KEY)

# 안전 설정: 금융 분석 시 차단되는 경우를 방지
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_fear_greed_index():
    try:
        fng = fear_and_greed.get()
        return {
            'value': int(fng.value),
            'description': fng.description
        }
    except Exception as e:
        print(f"Error fetching Fear & Greed Index: {e}")
        return None

def analyze_sentiment(fng_data):
    print("Analyzing market sentiment with AI...")
    prompt = f"""
    당신은 글로벌 금융 시장 분석 전문가입니다. 
    당신의 역할은 CNN Fear & Greed Index 정보를 바탕으로 현재 시장의 심리 상태를 객관적으로 브리핑하는 것입니다.
    이것은 특정 자산에 대한 매수/매도 추천이 아니며, 데이터 기반의 기술적 심리 분석임을 명확히 인지하세요.

    [지수 정보]
    - 지수 값: {fng_data['value']} (0: 극도의 공포, 100: 극도의 탐욕)
    - 상태: {fng_data['description']}

    [요청 사항]
    0. 중립적인 해석을 해주세요.
    1. 현재 시장의 심리 상태를 아주 핵심만 짚어서 아주 쉽게 설명해 주세요. (금융 지식이 없는 사람도 이해할 수 있게)
    2. 분석(analysis) 내용은 긴 줄글이 아닌, 가독성이 좋은 3~4개의 짧은 문장 또는 불렛 포인트 형식으로 작성해 주세요.
    3. 전문 용어보다는 '비유'나 '일상적인 단어'를 사용해 주세요.
    4. 투자자가 지금 당장 가져야 할 마음가짐을 조언(advice)에 담아주세요.
    5. 전체적으로 "오늘 시장 분위기는 이렇습니다"라고 가볍게 브리핑하는 톤앤매너를 유지해 주세요.
    6. 차분한 말투로 작성해 주세요.
    7. 조언할땐 ~하세요가 아닌 ~하는것이 좋아보여요, ~하는게 어때요? 등의 부드러운 어투를 사용해 주세요.
    8. 높임말 사용.
    9. 조언 1에선 조언 2,3과 다르게 문장에 알맞는 이모지 작성, 35자 이내로 간결하게 작성.
    10. 사용자가 네 의견만 맹신하여 따라하지 않도록 문장을 작성
    11. 특수문자 **같은 물결표는 사용 금지**입니다. 텍스트만 작성해 주세요.
    [JSON 형식]
    {{
        "title": "오늘의 시장 분위기를 한 문장으로 요약한 제목(~,-,! 사용금지)",
        "analysis": "핵심 요약 내용 (문장별로 줄바꿈 적용)",
        "advice": ["조언1", "조언2", "조언3"]
    }}
    """
    
    for attempt in range(3):
        try:
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"},
                safety_settings=safety_settings
            )
            
            if response.candidates and response.candidates[0].content.parts:
                res_data = json.loads(response.text)
                if isinstance(res_data, list):
                    return res_data[0]
                return res_data
            else:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "No candidates"
                print(f"Attempt {attempt + 1}: AI response empty. Reason: {finish_reason}")
                continue
                
        except Exception as e:
            print(f"Attempt {attempt + 1} error in AI analysis: {e}")
            if attempt == 2:
                break

    return {
        "title": "시장 분위기를 읽는 중입니다",
        "analysis": "현재 AI 분석이 일시적으로 지연되고 있습니다. 지수 데이터는 정상적으로 업데이트되었으니 수치를 확인해 주세요.",
        "advice": ["주요 기술 지표 위주로 참고해 보세요.", "잠시 후 다시 시도해 주세요.", "차분하게 시장을 지켜보는 것이 좋아 보여요."]
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
        
        # 푸시 알림 전송
        try:
            val = data['value']
            desc = data['description']
            send_push_to_all(
                title=f"📊 공포 탐욕 지수: {val} ({desc})",
                body=f"현재 글로벌 시장 심리는 '{desc}' 단계입니다. AI의 분석을 확인해보세요.",
                url="/fear-greed"
            )
        except Exception as e:
            print(f"Failed to send push: {e}")
            
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
