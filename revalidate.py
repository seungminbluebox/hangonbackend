import os
import requests
from dotenv import load_dotenv

load_dotenv()

REVALIDATE_SECRET = os.getenv("REVALIDATE_SECRET")
# 기본 URL. 환경 변수에 없으면 프로덕션 URL 사용
BASE_URL = os.getenv("FRONTEND_URL", "https://hangon.co.kr")

def revalidate_path(path):
    """
    Vercel에 특정 경로의 페이지를 다시 생성하도록 요청합니다.
    """
    if not REVALIDATE_SECRET:
        print("⚠ REVALIDATE_SECRET이 설정되지 않았습니다. 갱신을 건너뜁니다.")
        return False
    
    try:
        url = f"{BASE_URL}/api/revalidate"
        params = {
            "secret": REVALIDATE_SECRET,
            "path": path
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            print(f"✅ 성공적으로 경로를 갱신했습니다: {path}")
            return True
        else:
            print(f"❌ 경로 갱신 실패: {path}, 상태 코드: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Revalidate API 호출 중 오류 발생: {e}")
        return False

def revalidate_tag(tag):
    """
    Vercel에 특정 태그가 달린 데이터를 사용하는 페이지들을 다시 생성하도록 요청합니다.
    """
    if not REVALIDATE_SECRET:
        print("⚠ REVALIDATE_SECRET이 설정되지 않았습니다. 갱신을 건너뜁니다.")
        return False
    
    try:
        url = f"{BASE_URL}/api/revalidate"
        params = {
            "secret": REVALIDATE_SECRET,
            "tag": tag
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            print(f"✅ 성공적으로 태그를 갱신했습니다: {tag}")
            return True
        else:
            print(f"❌ 태그 갱신 실패: {tag}, 상태 코드: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Revalidate API 호출 중 오류 발생: {e}")
        return False
