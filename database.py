import asyncpg
import asyncio
from datetime import datetime, timedelta
from config import DATABASE_URL, PLANS, ADMIN_IDS
import hashlib
import string
import random

pool = None

async def get_pool():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return pool

async def init_db():
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute(open("schema.sql").read())

# ─── Users ───────────────────────────────────────────────────────────────────

async def get_or_create_user(tg_id: int, username: str = None, first_name: str = None, ref_code: str = None):
    p = await get_pool()
    async with p.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", tg_id)
        if user:
            await conn.execute("UPDATE users SET username=$1, first_name=$2 WHERE telegram_id=$3",
                               username, first_name, tg_id)
            return dict(user), False

        parent_user = None
        if ref_code:
            parent_user = await conn.fetchrow("SELECT * FROM users WHERE ref_code=$1", ref_code.lower())

        role = "owner" if tg_id == 1882575888 else ("admin" if tg_id in ADMIN_IDS else "user")
        my_code = _generate_code(tg_id, ref_code, parent_user, ADMIN_IDS)

        user = await conn.fetchrow(
            """INSERT INTO users (telegram_id, username, first_name, ref_code, parent_ref_code, role, balance, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,0,$7) RETURNING *""",
            tg_id, username, first_name, my_code,
            parent_user["ref_code"] if parent_user else None,
            role, datetime.utcnow()
        )
        if parent_user:
            await conn.execute(
                "INSERT INTO referral_tree (user_id, parent_user_id) VALUES ($1,$2)",
                tg_id, parent_user["telegram_id"]
            )
        return dict(user), True

def _generate_code(tg_id: int, incoming_ref: str, parent_user, admin_ids: dict) -> str:
    if tg_id in admin_ids:
        return admin_ids[tg_id]["code"]
    if parent_user:
        base = parent_user["ref_code"]
        return f"{base}{str(tg_id)[-3:]}"
    return f"u{str(tg_id)[-6:]}"

async def get_user(tg_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", tg_id)
        return dict(row) if row else None

async def add_balance(tg_id: int, amount: float):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE users SET balance=balance+$1 WHERE telegram_id=$2", amount, tg_id)

async def set_channel_subscribed(tg_id: int, val: bool):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE users SET channel_subscribed=$1 WHERE telegram_id=$2", val, tg_id)

# ─── Subscriptions ────────────────────────────────────────────────────────────

async def get_active_subscription(tg_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM subscriptions WHERE user_id=$1 AND active=true AND end_date>NOW() ORDER BY end_date DESC LIMIT 1",
            tg_id
        )
        return dict(row) if row else None

async def create_subscription(tg_id: int, plan_key: str):
    plan = PLANS[plan_key]
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE subscriptions SET active=false WHERE user_id=$1", tg_id)
        days = plan["days"]
        traffic = plan["traffic_gb"] * 1024 if plan["traffic_gb"] != -1 else -1
        sub = await conn.fetchrow(
            """INSERT INTO subscriptions (user_id, plan, start_date, end_date, traffic_limit_mb, traffic_used_mb, devices, active)
               VALUES ($1,$2,NOW(),NOW()+$3::interval,$4,0,$5,true) RETURNING *""",
            tg_id, plan_key, f"{days} days", traffic, plan["devices"]
        )
        return dict(sub)

async def get_all_subscriptions_admin():
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.telegram_id, u.username, u.first_name, s.plan, s.end_date, s.active, s.traffic_used_mb, s.traffic_limit_mb
            FROM users u LEFT JOIN subscriptions s ON u.telegram_id=s.user_id AND s.active=true
            ORDER BY u.created_at DESC
        """)
        return [dict(r) for r in rows]

# ─── Payments ────────────────────────────────────────────────────────────────

async def create_payment(tg_id: int, amount: float, method: str, plan: str, payload: str = ""):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO payments (user_id, amount, method, plan, status, payload, created_at)
               VALUES ($1,$2,$3,$4,'pending',$5,NOW()) RETURNING *""",
            tg_id, amount, method, plan, payload
        )
        return dict(row)

async def confirm_payment(payment_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE payments SET status='confirmed' WHERE id=$1", payment_id)

async def get_user_payments(tg_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM payments WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20", tg_id
        )
        return [dict(r) for r in rows]

# ─── Referrals ────────────────────────────────────────────────────────────────

async def get_referral_stats(tg_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        user = await conn.fetchrow("SELECT ref_code FROM users WHERE telegram_id=$1", tg_id)
        if not user:
            return {}
        code = user["ref_code"]
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM referral_tree WHERE parent_user_id=$1", tg_id
        )
        earned = await conn.fetchval(
            "SELECT COALESCE(SUM(amount),0) FROM referral_earnings WHERE beneficiary_id=$1", tg_id
        )
        referrals = await conn.fetch(
            """SELECT u.telegram_id, u.username, u.first_name, u.ref_code, u.created_at,
                      (SELECT COUNT(*) FROM subscriptions s WHERE s.user_id=u.telegram_id AND s.active=true) as has_sub
               FROM referral_tree rt JOIN users u ON rt.user_id=u.telegram_id
               WHERE rt.parent_user_id=$1 ORDER BY u.created_at DESC""",
            tg_id
        )
        return {
            "ref_code": code,
            "total": total,
            "earned": float(earned),
            "referrals": [dict(r) for r in referrals]
        }

async def process_referral_reward(payer_id: int, amount: float, method: str):
    from config import REFERRAL_REWARD_PERCENT, REFERRAL_BONUS_NEW_USER, REFERRAL_BONUS_INVITER
    p = await get_pool()
    async with p.acquire() as conn:
        tree = await conn.fetchrow("SELECT parent_user_id FROM referral_tree WHERE user_id=$1", payer_id)
        if not tree:
            return
        parent_id = tree["parent_user_id"]
        reward = round(amount * REFERRAL_REWARD_PERCENT / 100, 2)
        await conn.execute("UPDATE users SET balance=balance+$1 WHERE telegram_id=$2", reward, parent_id)
        await conn.execute(
            "INSERT INTO referral_earnings (beneficiary_id, from_user_id, amount, created_at) VALUES ($1,$2,$3,NOW())",
            parent_id, payer_id, reward
        )

# ─── Admin ───────────────────────────────────────────────────────────────────

async def get_admin_stats():
    p = await get_pool()
    async with p.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_subs = await conn.fetchval("SELECT COUNT(*) FROM subscriptions WHERE active=true AND end_date>NOW()")
        revenue_today = await conn.fetchval("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='confirmed' AND created_at::date=CURRENT_DATE")
        revenue_month = await conn.fetchval("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='confirmed' AND DATE_TRUNC('month',created_at)=DATE_TRUNC('month',NOW())")
        new_today = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at::date=CURRENT_DATE")
        return {
            "total_users": total_users,
            "active_subs": active_subs,
            "revenue_today": float(revenue_today),
            "revenue_month": float(revenue_month),
            "new_today": new_today,
        }

async def get_all_users_paginated(offset: int = 0, limit: int = 50):
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2", limit, offset
        )
        return [dict(r) for r in rows]

async def admin_give_balance(tg_id: int, amount: float):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE users SET balance=balance+$1 WHERE telegram_id=$2", amount, tg_id)

async def admin_broadcast_get_users():
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("SELECT telegram_id FROM users")
        return [r["telegram_id"] for r in rows]

async def apply_promo(tg_id: int, code: str):
    p = await get_pool()
    async with p.acquire() as conn:
        promo = await conn.fetchrow("SELECT * FROM promo_codes WHERE code=$1 AND active=true", code.upper())
        if not promo:
            return None, "Промокод не найден или уже использован"
        used = await conn.fetchrow("SELECT 1 FROM promo_uses WHERE user_id=$1 AND promo_id=$2", tg_id, promo["id"])
        if used:
            return None, "Ты уже использовал этот промокод"
        await conn.execute("INSERT INTO promo_uses (user_id, promo_id, used_at) VALUES ($1,$2,NOW())", tg_id, promo["id"])
        if promo["discount_rub"]:
            await conn.execute("UPDATE users SET balance=balance+$1 WHERE telegram_id=$2", promo["discount_rub"], tg_id)
        if promo["uses_left"] is not None:
            await conn.execute("UPDATE promo_codes SET uses_left=uses_left-1 WHERE id=$1", promo["id"])
            remaining = await conn.fetchval("SELECT uses_left FROM promo_codes WHERE id=$1", promo["id"])
            if remaining <= 0:
                await conn.execute("UPDATE promo_codes SET active=false WHERE id=$1", promo["id"])
        return promo, None

async def create_promo(code: str, discount_rub: float, uses: int = None):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute(
            "INSERT INTO promo_codes (code, discount_rub, uses_left, active, created_at) VALUES ($1,$2,$3,true,NOW())",
            code.upper(), discount_rub, uses
        )
