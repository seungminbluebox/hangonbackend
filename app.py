import feedparser
from google import genai
from supabase import create_client, Client
import json
import os
from dotenv import load_dotenv

# 1. 환경 변수 및 클라이언트 설정
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. 뉴스 수집 함수 (구글 뉴스 RSS 통일)
def fetch_all_candidate_news():
    candidates = {"KR": [], "US": [], "Global": []}

    # A. 한국 (구글 뉴스 - 경제 키워드)
    try:
        # 더 정확한 경제 뉴스 수집을 위해 키워드 보강
        kr_feed = feedparser.parse("https://news.google.com/rss/search?q=%EA%B2%BD%EC%A0%9C+%EA%B8%88%EB%A6%AC+%EC%8B%9C%EC%9E%A5+when:1d&hl=ko&gl=KR&ceid=KR:ko")
        for entry in kr_feed.entries[:15]:
            candidates["KR"].append({"title": entry.title, "url": entry.link})
    except Exception as e:
        print(f"한국 뉴스 수집 에러: {e}")

    # B. 미국 (구글 뉴스 US Business)
    try:
        us_feed = feedparser.parse("https://news.google.com/rss/search?q=business+finance+stock+market+when:1d&hl=en-US&gl=US&ceid=US:en")
        for entry in us_feed.entries[:15]:
            candidates["US"].append({"title": entry.title, "url": entry.link})
    except Exception as e:
        print(f"미국 뉴스 수집 에러: {e}")

    # C. 글로벌 (구글 뉴스 World Economy)
    try:
        global_feed = feedparser.parse("https://news.google.com/rss/search?q=World+Economy+Outlook+when:1d&hl=ko&gl=KR&ceid=KR:ko")
        for entry in global_feed.entries[:15]:
            candidates["Global"].append({"title": entry.title, "url": entry.link})
    except Exception as e:
        print(f"글로벌 뉴스 수집 에러: {e}")

    return candidates


# 3. Gemini 필터링 및 요약 함수
def get_curated_summary(news_list):
    all_candidates_text = ""
    for cat in ["KR", "US", "Global"]:
        all_candidates_text += f"\n[{cat} 뉴스 후보]\n"
        for i, item in enumerate(news_list[cat]):
            all_candidates_text += f"ID: {cat}_{i}\n제목: {item['title']}\nURL: {item['url']}\n\n"

    prompt = f"""
    당신은 글로벌 경제 전문 애널리스트입니다. 아래 제공된 기사 후보들 중에서 
    반드시 [한국 2개, 미국 2개, 글로벌 1개]의 비율을 지켜 총 5개의 핵심 뉴스를 선정하고 요약하세요.

    [뉴스 후보 목록]
    {all_candidates_text}
    
    [선정 기준]
    1. 뉴스가 시장에 미치는 영향력이 큰가?
    2. 투자자들이 반드시 알아야 할 핵심 정보인가(ex 금리 변동, 정책 발표, 환율 변동 등)?
    3. 단기적 이슈가 아닌 중장기적 관점에서 중요한가?
    4. 국가 정책, 금리, 환율에 직접적인 영향을 주는가?
    5. 글로벌 빅테크나 주요 산업의 판도를 바꿀 만한 사건인가?
    6. 중복되는 내용 없이 다양한 이슈를 다루고 있는가?
    7. 신뢰할 수 있는 출처에서 나온 뉴스인가?
    8. 결과물은 반드시 한국 2개, 미국 2개, 글로벌 1개여야 합니다.
    9. 기자의 의견이 아닌 객관적 사실에 기반한 뉴스여야 합니다.
    10. 모든 요약은 한국어로 작성하세요.
    11. 총 5개를 선정: 한국 2개, 미국 2개, 글로벌 1개 필수.
    12. 뉴스 선정 기준: 중장기적 시장 영향력, 투자 인사이트가 풍부한 뉴스.
    13. 요약 스타일: '~함', '~음'으로 끝나는 개조식 요약 (3개 포인트).
    14. 반드시 제공된 원본 URL을 사용하도록 합니다.
    15. 각 뉴스 후보는 ID로 구분되어 있으며, 제목과 URL이 한 쌍입니다.
    16. 선정된 뉴스의 요약을 작성할 때, 해당 ID에 귀속된 원본 URL을 절대로 변경하거나 다른 제목과 섞지 마세요.

    [출력 형식]
    반드시 JSON 스키마 형식을 준수하세요.
    [
      {{
        "category": "KR | US | Global",
        "keyword": "이슈를 직관적으로 설명하는 문장",
        "summary": "- 요약 내용 1\\n- 요약 내용 2\\n- 시장 전망/시사점",
        "links": [{{ "title": "선택한 후보의 원본 제목", "url": "선택한 후보의 정확한 ID 대응 URL" }}]
      }}
    ]
    """

    response = client.models.generate_content(
        model="gemini-2.0-flash", # 속도와 성능이 균형 잡힌 모델
        contents=prompt,
        config={'response_mime_type': 'application/json'}
    )
    
    return json.loads(response.text)

# 4. 실행 로직
def main():
    print("🚀 뉴스 수집 시작...")
    candidates = fetch_all_candidate_news()
    if not candidates:
        print("❌ 수집된 뉴스가 없습니다.")
        return
    print(f"🧐 {len(candidates)}개의 후보 중 5개 선별 및 요약 중...")
    try:
        final_news = get_curated_summary(candidates)
        # 5. Supabase 저장
        for item in final_news:
            supabase.table("daily_news").insert(item).execute()
        
        print("✅ 성공적으로 DB에 저장되었습니다.")
    except Exception as e:
        print(f"❌ 요약 및 저장 중 오류 발생: {e}")

main()