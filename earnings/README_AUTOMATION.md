# """

# 📅 Earnings Calendar 자동화 운영 가이드

세 가지 스크립트의 역할과 실행 주기를 정의합니다.

1️⃣ earningsTracker.py (어닝 일정 수집)

- 목적: 미래(발표 예정) 실적 데이터 수집
- 실행 주기: 매주 월요일 오전 (또는 주 3회)
- 역할: 새로운 어닝 스케줄 감지 및 DB 추가
- 데이터: eps_estimate, revenue_estimate만 채움
- 특징: 과거 데이터는 스킵 (is_past=True면 continue)

2️⃣ earningsUpdater.py (과거 실적 업데이트)

- 목적: 발표 완료된 실적의 실제값 채우기
- 실행 주기: 매일 오후/저녁 (19:00~22:00)
- 역할: eps_actual, revenue_actual 업데이트
- 데이터: 과거(date <= today) 레코드만 스캔
- 특징: yfinance의 ~7일 지연을 보정하여 재시도

3️⃣ monitoredStocksManager.py (인덱스 변화 추적)

- 목적: S&P 100, KOSPI 50 구성 변화 감지
- 실행 주기: 월 1회 (월 첫 주) 또는 분기 1회
- 역할: 편입/편출 종목 추적, soft delete 처리
- 데이터: monitored_stocks 테이블 동기화
- 특징: 편출 회사는 soft delete (status='inactive')

==============================================
🗓️ 권장 실행 주기 (Cron 기반)
==============================================

# 어닝 일정 수집 (주 3회: 월/수/금 9:00)

0 9 \* \* 1,3,5 cd /path/to/hangon && python backend/earnings/earningsTracker.py

# 과거 실적 업데이트 (매일 20:00)

0 20 \* \* \* cd /path/to/hangon && python backend/earnings/earningsUpdater.py

# 인덱스 변화 추적 (월 1회: 첫 주 월요일 10:00)

0 10 ? \* MON#1 cd /path/to/hangon && python backend/earnings/monitoredStocksManager.py

==============================================
📊 데이터 흐름
==============================================

1. 초기 설정 (2026-02-07)
   - earningsTracker.py 실행 (모든 미래 데이터 수집)
   - monitoredStocksManager.py 실행 (monitored_stocks 초기화)
     ✅ 결과: earnings_calendar에 미래 데이터, monitored_stocks에 활성 종목

2. 일일 운영
   earningsTracker (주 3회)
   ↓ 새로운 어닝 감지
   earnings_calendar 업데이트 (미래만)
   ↓
   earningsUpdater (매일)
   ↓ 과거 실적 스캔
   earnings_calendar 업데이트 (eps_actual, revenue_actual)

3. 분기별 유지보수
   monitoredStocksManager (월 1회)
   ↓ 인덱스 구성 비교
   편입 회사: 추가 (과거 데이터 없음)
   편출 회사: soft delete (기존 데이터 유지)

==============================================
⚠️ 주의사항
==============================================

1. yfinance 지연 특성:
   - earnings_dates: 발표 후 30~40일 후 삭제
   - quarterly_income_stmt: 발표 후 ~7일 지연

2. 중복 방지:
   - earningsTracker는 (symbol, date) 복합키로 upsert
   - 같은 일정이 여러 번 수집되어도 덮어씀

3. 데이터 무결성:
   - earningsUpdater가 이미 있는 값을 덮어쓰지 않음
   - revenue_actual는 처음 채워질 때만 저장

4. 신규 편입 회사:
   - 과거 데이터 없이 시작 (우리는 과거 데이터 신경 안 씀)
   - 미래 일정은 자동으로 earningsTracker가 수집

==============================================
🔧 수동 명령어
==============================================

# 전체 리셋 (초기 설정 또는 큰 변화 시)

python backend/earnings/monitoredStocksManager.py
python backend/earnings/earningsTracker.py

# 과거 데이터만 재업데이트 (특정 종목)

python backend/earnings/earningsUpdater.py

# 테스트 (단일 종목 검증)

python backend/earnings/test.py

==============================================
"""

print(**doc**)
