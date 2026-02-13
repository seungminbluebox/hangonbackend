import os
import json
import time
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

def dispatch_queued_notifications():
    """
    notification_queue 테이블에 쌓인 알림들을 사용자들에게 발송합니다.
    """
    if not VAPID_PRIVATE_KEY:
        print("VAPID_PRIVATE_KEY가 설정되지 않았습니다.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 큐 데이터 가져오기 (구독 정보와 함께 가져오기 위해 조인 수행)
    # subscription_id를 통해 push_subscriptions 테이블의 정보를 가져옵니다.
    try:
        # Supabase API에서 foreign key 관계가 설정되어 있다면 아래와 같이 가져올 수 있습니다.
        response = supabase.table("notification_queue").select("*, push_subscriptions(subscription)").execute()
        queued_items = response.data
    except Exception as e:
        print(f"큐 데이터를 불러오는 중 에러 발생: {e}")
        return

    if not queued_items:
        print("발송할 대기 중인 알림이 없습니다.")
        return

    print(f"총 {len(queued_items)}개의 대기 중인 알림을 발송합니다.")

    processed_ids = []

    for item in queued_items:
        try:
            # 조인된 데이터에서 구독 정보 추출
            sub_info = item.get("push_subscriptions", {}).get("subscription")
            if not sub_info:
                print(f"구독 정보가 없는 알림 스킵 (Queue ID: {item['id']})")
                processed_ids.append(item["id"])
                continue

            webpush(
                subscription_info=sub_info,
                data=json.dumps({
                    "title": item["title"],
                    "body": item["body"],
                    "url": item["url"]
                }),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS.copy(),
                ttl=86400,
                headers={"Urgency": "high"}
            )
            print(f"알림 발송 성공: {item['id']}")
            processed_ids.append(item["id"])
            
            # 너무 빠른 발송 방지를 위해 아주 짧은 시간 대기
            time.sleep(0.05)
            
        except WebPushException as ex:
            print(f"알림 발송 실패 (Queue ID: {item['id']}): {ex}")
            # 전송 실패하더라도 리스트에 추가하여 큐에서는 지우는 것이 일반적 (재시도 로직은 복잡해질 수 있음)
            processed_ids.append(item["id"])
        except Exception as e:
            print(f"처리 중 에러 발생: {e}")

    # 발송 완료된 항목들 큐에서 삭제
    if processed_ids:
        try:
            # .in_() 필터 사용 (Supabase Python client 형식)
            supabase.table("notification_queue").delete().in_("id", processed_ids).execute()
            print(f"발송 완료된 {len(processed_ids)}개의 항목이 큐에서 삭제되었습니다.")
        except Exception as e:
            print(f"큐 삭제 처리 중 에러 발생: {e}")

if __name__ == "__main__":
    dispatch_queued_notifications()
