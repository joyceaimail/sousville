-- ═══════════════════════════════════════════════════════════
-- 舒肥底家 SousVille — Supabase 建表 SQL
-- 請到 Supabase Dashboard → SQL Editor 貼上執行
-- ═══════════════════════════════════════════════════════════

-- 1. 管理員帳號
CREATE TABLE IF NOT EXISTS admin_users (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 2. 會員等級
CREATE TABLE IF NOT EXISTS member_tiers (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email           TEXT,
    notion_user_id  TEXT,
    tier            TEXT NOT NULL DEFAULT '一般' CHECK (tier IN ('一般', 'VIP', 'VVIP')),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (notion_user_id)
);

-- 3. 訂單
CREATE TABLE IF NOT EXISTS orders (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_email  TEXT,
    amount      NUMERIC(10,2) DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 4. 折扣碼
CREATE TABLE IF NOT EXISTS discount_codes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,
    discount_type   TEXT NOT NULL DEFAULT 'percentage' CHECK (discount_type IN ('percentage', 'fixed')),
    value           INTEGER NOT NULL DEFAULT 0,
    max_uses        INTEGER,
    min_order       NUMERIC(10,2) DEFAULT 0,
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    used_count      INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ═══ RLS（Row Level Security）═══
ALTER TABLE admin_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE member_tiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE discount_codes ENABLE ROW LEVEL SECURITY;

-- 用 service_role key 可以繞過 RLS，所以不需要特別 policy
-- 但如果未來要用 anon key 讀取，可加：
-- CREATE POLICY "Allow read" ON discount_codes FOR SELECT USING (true);

-- ═══ 預設管理員帳號 ═══
-- 請把 'admin' 改成你想用的管理員帳號
INSERT INTO admin_users (username) VALUES ('admin')
ON CONFLICT (username) DO NOTHING;
