-- LiliumVPN Database Schema
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(100),
    first_name VARCHAR(200),
    ref_code VARCHAR(50) UNIQUE,
    parent_ref_code VARCHAR(50),
    role VARCHAR(20) DEFAULT 'user',  -- owner / admin / user
    balance DECIMAL(10,2) DEFAULT 0,
    channel_subscribed BOOLEAN DEFAULT false,
    email VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id),
    plan VARCHAR(50),
    start_date TIMESTAMP DEFAULT NOW(),
    end_date TIMESTAMP,
    traffic_limit_mb BIGINT DEFAULT 10240,  -- -1 = unlimited
    traffic_used_mb BIGINT DEFAULT 0,
    devices INT DEFAULT 1,
    active BOOLEAN DEFAULT true,
    vpn_key TEXT,
    server_id INT
);

CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id),
    amount DECIMAL(10,2),
    method VARCHAR(50),  -- stars / crypto / ckassa / balance
    plan VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',  -- pending / confirmed / failed
    payload TEXT,
    telegram_payment_id VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS referral_tree (
    id SERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE REFERENCES users(telegram_id),
    parent_user_id BIGINT REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS referral_earnings (
    id SERIAL PRIMARY KEY,
    beneficiary_id BIGINT REFERENCES users(telegram_id),
    from_user_id BIGINT REFERENCES users(telegram_id),
    amount DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS servers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    location VARCHAR(100),
    flag VARCHAR(10),
    host VARCHAR(200),
    active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS vpn_keys (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id),
    server_id INT REFERENCES servers(id),
    sub_url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE,
    discount_rub DECIMAL(10,2) DEFAULT 0,
    uses_left INT,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS promo_uses (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id),
    promo_id INT REFERENCES promo_codes(id),
    used_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id SERIAL PRIMARY KEY,
    sender_id BIGINT,
    message TEXT,
    sent_at TIMESTAMP DEFAULT NOW(),
    total_sent INT DEFAULT 0
);

-- Sample servers (update with real VPN server data)
INSERT INTO servers (name, location, flag, host, active) VALUES
('DE-FRA-ND-01', 'Frankfurt, Germany', '🇩🇪', 'de1.liliumvpn.net', true),
('NL-AMS-ND-01', 'Amsterdam, Netherlands', '🇳🇱', 'nl1.liliumvpn.net', true),
('FI-HEL-ND-01', 'Helsinki, Finland', '🇫🇮', 'fi1.liliumvpn.net', true)
ON CONFLICT DO NOTHING;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_ref_tree_parent ON referral_tree(parent_user_id);
