import os
import sys
import json
from pywebpush import webpush, WebPushException
from supabase import create_client, Client
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {
    "sub": "mailto:boxmagic25@gmail.com"
}

def send_manual_announcement(title, body, url="/", test_mode=False):
    """
    구독 설정이 하나라도 'true'인 모든 사용자에게 공지 알림을 전송합니다.
    """
    if not VAPID_PRIVATE_KEY:
        print("VAPID_PRIVATE_KEY가 설정되지 않았습니다.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    print(f"알림 데이터를 불러오는 중... (필터링: 하나 이상의 알림 설정 활성화)")
    
    try:
        # 모든 구독 정보 가져오기
        # 참고: 복잡한 JSONB 필터링은 파이썬에서 처리하거나 rpc를 사용해야 함
        response = supabase.table("push_subscriptions").select("*").execute()
        all_subscriptions = response.data
    except Exception as e:
        print(f"구독 정보를 불러오는 중 에러 발생: {e}")
        return

    # 하나라도 true인 사용자 필터링
    target_subscriptions = []
    for sub in all_subscriptions:
        prefs = sub.get("preferences", {})
        # prefs가 딕셔너리이고, 값 중 하나라도 True (또는 "true")인 경우 포함
        if any(val is True or str(val).lower() == "true" for val in prefs.values()):
            target_subscriptions.append(sub)

    count = len(target_subscriptions)
    print(f"검색 완료. 총 {count}명의 대상자에게 알림을 전송합니다.")
    
    if test_mode:
        print("--- 테스트 모드: 실제 발송을 하지 않고 종료합니다. ---")
        return

    if count == 0:
        print("전송할 대상이 없습니다.")
        return

    # 확인 절차
    confirm = input(f"정말로 위 수치의 사용자들에게 알림을 보낼까요? (y/n): ")
    if confirm.lower() != 'y':
        print("취소되었습니다.")
        return

    success_count = 0
    fail_count = 0

    for sub_record in target_subscriptions:
        try:
            subscription_info = sub_record["subscription"]
            
            webpush(
                subscription_info=subscription_info,
                data=json.dumps({
                    "title": title,
                    "body": body,
                    "url": url
                }),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS.copy(),
                ttl=86400,
                headers={"Urgency": "high"}
            )
            success_count += 1
            print(f"[{success_count}/{count}] 전송 성공: {sub_record['id']}")
        except WebPushException as ex:
            fail_count += 1
            if ex.response is not None:
                print(f"전송 실패 (ID: {sub_record['id']}, Status: {ex.response.status_code})")
                if ex.response.status_code in [404, 410]:
                    supabase.table("push_subscriptions").delete().eq("id", sub_record["id"]).execute()
                    print(f"   ㄴ 만료된 구독 자동 삭제됨.")
            else:
                print(f"전송 실패 (ID: {sub_record['id']}): {ex}")
        except Exception as e:
            fail_count += 1
            print(f"기타 에러 발생 (ID: {sub_record['id']}): {e}")

    print("\n================================")
    print(f"최종 결과")
    print(f"성공: {success_count}")
    print(f"실패: {fail_count}")
    print("================================\n")

if __name__ == "__main__":
    # ========================================================
    # [수정 영역] 발송할 알림 내용을 직접 입력하세요.
    # ========================================================
    TITLE = "새로운 업데이트 안내 🎉"
    BODY = "한미 양국간 증시 커플링 지수 업데이트되었습니다. 양국 동시 운영날마다 업데이트 됩니다!"
    URL = "/market-correlation"  # 클릭 시 이동할 페이지 (기본값: "/")
    IS_TEST_MODE = False  # True: 대상자 인원수만 확인 | False: 실제 발송
    # ========================================================

    send_manual_announcement(
        title=TITLE,
        body=BODY,
        url=URL,
        test_mode=IS_TEST_MODE
    )
