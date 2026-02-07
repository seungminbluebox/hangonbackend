-- =============================================
-- Earnings Calendar 자동화를 위한 DB 스키마
-- =============================================

-- 1) earnings_calendar (이미 있음 - 확인용)
-- 필수 컬럼:
-- - symbol (문자, PK)
-- - date (날짜, PK)
-- - eps_estimate (숫자)
-- - eps_actual (숫자, NULL 허용)
-- - revenue_estimate (숫자)
-- - revenue_estimate_formatted (문자)
-- - revenue_actual (숫자, NULL 허용)
-- - revenue_actual_formatted (문자)
-- - updated_at (타임스탬프)

-- 기존 테이블 확인 쿼리:
-- PRAGMA table_info(earnings_calendar);

-- =============================================
-- 2) monitored_stocks (신규 생성 필요)
-- =============================================

CREATE TABLE IF NOT EXISTS monitored_stocks (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    symbol VARCHAR(20) UNIQUE NOT NULL,           -- 'AAPL', '005930.KS' 등
    company_name VARCHAR(255),                    -- '애플', '삼성전자' 등
    country VARCHAR(2) CHECK (country IN ('US', 'KR')),
    status VARCHAR(20) DEFAULT 'active'           -- 'active', 'inactive'
        CHECK (status IN ('active', 'inactive')),
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    removed_at TIMESTAMP WITH TIME ZONE,          -- soft delete 날짜
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스 추가 (조회 속도 최적화)
CREATE INDEX IF NOT EXISTS idx_monitored_stocks_status 
    ON monitored_stocks(status);
CREATE INDEX IF NOT EXISTS idx_monitored_stocks_country 
    ON monitored_stocks(country);

-- =============================================
-- 3) earnings_calendar에 필요한 추가 정보
-- =============================================

-- 기존 테이블에 컬럼 추가 (이미 추가됨 확인)
-- ALTER TABLE earnings_calendar 
-- ADD COLUMN IF NOT EXISTS eps_actual FLOAT;
-- ADD COLUMN IF NOT EXISTS revenue_actual FLOAT;
-- ADD COLUMN IF NOT EXISTS revenue_estimate_formatted VARCHAR(50);
-- ADD COLUMN IF NOT EXISTS revenue_actual_formatted VARCHAR(50);

-- =============================================
-- 4) 데이터 초기화 쿼리 (첫 실행 시)
-- =============================================

-- earnings_calendar에서 과거 데이터 확인
-- SELECT count(*), country 
-- FROM earnings_calendar 
-- WHERE date < CURRENT_DATE
-- GROUP BY country;

-- 과거 데이터 중 revenue_actual이 NULL인 것들
-- SELECT symbol, date, eps_actual, revenue_actual, revenue_actual_formatted
-- FROM earnings_calendar
-- WHERE date < CURRENT_DATE
--   AND revenue_actual IS NULL
-- LIMIT 20;

-- monitored_stocks 초기화 (첫 실행 후)
-- INSERT INTO monitored_stocks (symbol, country, status)
-- SELECT DISTINCT symbol, country, 'active'
-- FROM earnings_calendar
-- ON CONFLICT (symbol) DO NOTHING;

-- =============================================
-- 5) 운영 쿼리
-- =============================================

-- 과거 데이터 중 실제값이 채워지지 않은 것
-- SELECT * FROM earnings_calendar
-- WHERE date < CURRENT_DATE 
--   AND (eps_actual IS NULL OR revenue_actual IS NULL)
-- ORDER BY date DESC;

-- 활성 종목 목록
-- SELECT * FROM monitored_stocks 
-- WHERE status = 'active'
-- ORDER BY country, symbol;

-- 편출된 종목 목록
-- SELECT * FROM monitored_stocks 
-- WHERE status = 'inactive'
-- ORDER BY removed_at DESC;
