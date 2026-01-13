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
        global_feed = feedparser.parse("https://news.google.com/rss/search?q=world+economy+when:1d&hl=ko&gl=KR&ceid=KR:ko")
        for entry in global_feed.entries[:15]:
            candidates["Global"].append({"title": entry.title, "url": entry.link})
    except Exception as e:
        print(f"글로벌 뉴스 수집 에러: {e}")

    return candidates


# 3. Gemini 필터링 및 요약 함수
def get_curated_summary(news_list):
    id_map = {}
    all_candidates_text = ""

    # [변경 사항] 모든 카테고리의 후보를 하나의 리스트로 통합하여 ID 부여
    global_index = 0
    for cat in ["KR", "US", "Global"]:
        for item in news_list[cat]:
            news_id = f"NEWS_{global_index}"
            id_map[news_id] = item
            # 출처 정보는 주지 않고 제목만 제공하여 내용에 집중하게 함
            all_candidates_text += f"ID: {news_id}\n제목: {item['title']}\n\n"
            global_index += 1

    prompt = f"""
    당신은 글로벌 경제 전문 애널리스트입니다. 아래 제공된 {global_index}개의 기사 후보들을 분석하여 
    오늘의 핵심 뉴스 5개를 선정하고 요약하세요.

    [뉴스 후보 목록]
    {all_candidates_text}
    
    [선정 기준]
    1. 뉴스가 시장에 미치는 영향력이 큰가?
    2. 전망, 예측보단 현재 상황을 명확히 설명하는 뉴스인가?
    3. 지수, 환율, 금리, 중요한 정책 위주의 뉴스인가?
    4. 국가 정책, 금리, 환율등 과 같은 주요 이슈인가?
    5. 글로벌 빅테크나 주요 산업의 판도를 바꿀 만한 사건인가?
    7. 신뢰할 수 있는 출처에서 나온 뉴스인가?
    8. 결과물은 반드시 한국 2개, 미국 2개, 글로벌 1개여야 합니다.
    9. 기자의 의견이 아닌 객관적 사실에 기반한 뉴스여야 합니다.
    10. 모든 요약은 한국어로 작성하세요.
    11. 총 5개를 선정: 한국 2개, 미국 2개, 글로벌 1개 필수.
    13. 요약 스타일: '~함', '~음'으로 끝나는 개조식 요약 (3개 포인트).
    16. 선정된 뉴스의 요약을 작성할 때, 해당 ID에 귀속된 원본 URL을 절대로 변경하거나 다른 제목과 섞지 마세요.
    17. 각 뉴스의 keyword에 마지막에 keyword에 맞는 이모지 사용(감정 이모지는 금지)
    18. 비슷한 주제는 피하고 다양한 이슈 선정
    결과에는 반드시 선정한 뉴스의 'ID'를 'selected_id' 필드에 담아 반환하세요.
    
    [카테고리 분류 및 선정 기준 (매우 중요)]
    1. 출처 언어와 상관없이 기사의 '핵심 주제'를 기준으로 카테고리를 다시 분류하세요.
       - KR: 대한민국 경제, 정책, 기업, 국내 시장 이슈
       - US: 미국 경제(Fed, 금리), 월스트리트, 미국 빅테크 기업 이슈
       - Global: 글로벌 매크로 트렌드, 국제기구(IMF, OECD), 중동/유럽 등 다국적 영향력 이슈
        [작성 가이드]
    - 모든 요약은 한국어로 작성하세요.
    - 요약 스타일: '~함', '~음'으로 끝나는 개조식 요약 (3개 포인트).
    - keyword: 이슈를 직관적으로 설명하는 문장 (추상적인 제목 대신 구체적인 사건 내용을 명시).
    - summary: 시장 전망/시사점 섹션에서도 실제 분석 내용을 구체적으로 작성.
    - 이모지: keyword 마지막에 주제와 어울리는 이모지 사용 (감정 이모지 제외).

    [출력 형식]
    반드시 JSON 스키마 형식을 준수하세요.
    [
      {{
        "category": "KR | US | Global",
        "keyword": "이슈를 직관적으로 설명하는 문장",
        "summary": "- 요약 내용 1\\n- 요약 내용 2\\n- 시장 전망/시사점",
        "selected_id": "선정한 뉴스의 ID (예: KR_0)"
      }}
    ]
    """

    response = client.models.generate_content(
        model="gemini-2.0-flash", # 속도와 성능이 균형 잡힌 모델
        contents=prompt,
        config={'response_mime_type': 'application/json'}
    )
    
    raw_results = json.loads(response.text)
    
    # 2. ID를 기반으로 원본 URL 매칭 (파이썬에서 수행)
    final_results = []
    for res in raw_results:
        news_id = res.get("selected_id")
        original_news = id_map.get(news_id)
        
        if original_news:
            res["links"] = [{"title": original_news["title"], "url": original_news["url"]}]
            # selected_id는 DB 저장 시 필요 없으므로 삭제 가능
            del res["selected_id"]
            final_results.append(res)
            
    return final_results

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