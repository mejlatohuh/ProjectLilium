from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import hmac, hashlib, json
from urllib.parse import unquote
from pydantic import BaseModel
from typing import Optional
import asyncio

from config import BOT_TOKEN, PLANS, ADMIN_IDS, OWNER_ID, WEBAPP_URL
import database as db
from bot import dp, bot

app = FastAPI(title="LiliumVPN API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Startup ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await db.init_db()

# ─── Auth ─────────────────────────────────────────────────────────────────────

def verify_initdata(init_data: str) -> dict:
    """Verify Telegram WebApp initData HMAC signature."""
    try:
        parsed = {}
        for part in init_data.split("&"):
            k, v = part.split("=", 1)
            parsed[k] = unquote(v)

        received_hash = parsed.pop("hash", "")
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new("WebAppData".encode(), BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            raise ValueError("Invalid hash")

        user_str = parsed.get("user", "{}")
        return json.loads(unquote(user_str))
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Unauthorized: {e}")

async def get_current_user(request: Request) -> dict:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="No auth")
    tg_user = verify_initdata(init_data)
    user = await db.get_user(tg_user["id"])
    if not user:
        user, _ = await db.get_or_create_user(
            tg_id=tg_user["id"],
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name")
        )
    return user

# ─── Webhook ─────────────────────────────────────────────────────────────────

@app.post("/webhook")
async def telegram_webhook(request: Request):
    from aiogram.types import Update
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}

# ─── User endpoints ───────────────────────────────────────────────────────────

@app.get("/api/me")
async def get_me(user=Depends(get_current_user)):
    sub = await db.get_active_subscription(user["telegram_id"])
    ref_stats = await db.get_referral_stats(user["telegram_id"])
    is_admin = user["telegram_id"] in ADMIN_IDS
    is_owner = user["telegram_id"] == OWNER_ID
    return {
        "user": {
            "telegram_id": user["telegram_id"],
            "username": user["username"],
            "first_name": user["first_name"],
            "ref_code": user["ref_code"],
            "balance": float(user["balance"]),
            "role": user["role"],
            "created_at": user["created_at"].isoformat() if user["created_at"] else None,
        },
        "subscription": {
            "plan": sub["plan"] if sub else None,
            "plan_name": PLANS.get(sub["plan"], {}).get("name") if sub else None,
            "end_date": sub["end_date"].isoformat() if sub else None,
            "traffic_limit_mb": sub["traffic_limit_mb"] if sub else 0,
            "traffic_used_mb": sub["traffic_used_mb"] if sub else 0,
            "devices": sub["devices"] if sub else 0,
            "active": bool(sub) and sub["active"],
            "vpn_key": sub.get("vpn_key") if sub else None,
        } if sub else None,
        "referrals": {
            "total": ref_stats.get("total", 0),
            "earned": ref_stats.get("earned", 0),
            "ref_code": ref_stats.get("ref_code", ""),
        },
        "is_admin": is_admin,
        "is_owner": is_owner,
    }

@app.get("/api/subscription")
async def get_subscription(user=Depends(get_current_user)):
    sub = await db.get_active_subscription(user["telegram_id"])
    if not sub:
        return {"subscription": None}
    return {"subscription": {
        "plan": sub["plan"],
        "plan_name": PLANS.get(sub["plan"], {}).get("name"),
        "end_date": sub["end_date"].isoformat(),
        "traffic_limit_mb": sub["traffic_limit_mb"],
        "traffic_used_mb": sub["traffic_used_mb"],
        "devices": sub["devices"],
        "active": sub["active"],
        "vpn_key": sub.get("vpn_key"),
    }}

@app.get("/api/plans")
async def get_plans():
    return {"plans": [
        {"key": k, **v} for k, v in PLANS.items() if k != "trial"
    ]}

@app.get("/api/balance")
async def get_balance(user=Depends(get_current_user)):
    payments = await db.get_user_payments(user["telegram_id"])
    return {
        "balance": float(user["balance"]),
        "payments": [
            {
                "id": p["id"],
                "amount": float(p["amount"]),
                "method": p["method"],
                "plan": p["plan"],
                "status": p["status"],
                "created_at": p["created_at"].isoformat()
            } for p in payments
        ]
    }

@app.get("/api/referrals")
async def get_referrals(user=Depends(get_current_user)):
    stats = await db.get_referral_stats(user["telegram_id"])
    bot_link = f"https://t.me/LiliumVPNBot?start=ref_{stats.get('ref_code', '')}"
    cabinet_link = f"{WEBAPP_URL}?ref={stats.get('ref_code', '')}"
    return {
        "ref_code": stats.get("ref_code", ""),
        "total": stats.get("total", 0),
        "earned": stats.get("earned", 0),
        "referrals": stats.get("referrals", []),
        "bot_link": bot_link,
        "cabinet_link": cabinet_link,
        "commission_percent": 25,
        "bonus_new": 50,
        "bonus_inviter": 50,
        "min_withdrawal": 200,
    }

class PromoRequest(BaseModel):
    code: str

@app.post("/api/promo/apply")
async def apply_promo(body: PromoRequest, user=Depends(get_current_user)):
    promo, error = await db.apply_promo(user["telegram_id"], body.code)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True, "discount": float(promo["discount_rub"]), "message": f"Промокод применён! +{promo['discount_rub']} ₽ на баланс"}

# ─── Admin endpoints ──────────────────────────────────────────────────────────

async def require_admin(user=Depends(get_current_user)):
    if user["telegram_id"] not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Admin only")
    return user

async def require_owner(user=Depends(get_current_user)):
    if user["telegram_id"] != OWNER_ID:
        raise HTTPException(status_code=403, detail="Owner only")
    return user

@app.get("/api/admin/stats")
async def admin_stats(user=Depends(require_admin)):
    stats = await db.get_admin_stats()
    return stats

@app.get("/api/admin/users")
async def admin_users(offset: int = 0, limit: int = 50, user=Depends(require_admin)):
    users = await db.get_all_users_paginated(offset, limit)
    return {"users": [
        {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in u.items()}
        for u in users
    ]}

@app.get("/api/admin/subscriptions")
async def admin_subs(user=Depends(require_admin)):
    subs = await db.get_all_subscriptions_admin()
    return {"subscriptions": [
        {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in s.items()}
        for s in subs
    ]}

class GiveBalanceRequest(BaseModel):
    target_id: int
    amount: float

@app.post("/api/admin/give-balance")
async def give_balance(body: GiveBalanceRequest, user=Depends(require_owner)):
    await db.admin_give_balance(body.target_id, body.amount)
    return {"ok": True}

class ActivateSubRequest(BaseModel):
    target_id: int
    plan: str

@app.post("/api/admin/activate-sub")
async def activate_sub(body: ActivateSubRequest, user=Depends(require_owner)):
    await db.create_subscription(body.target_id, body.plan)
    return {"ok": True}

class BroadcastRequest(BaseModel):
    message: str

@app.post("/api/admin/broadcast")
async def broadcast(body: BroadcastRequest, user=Depends(require_owner)):
    users = await db.admin_broadcast_get_users()
    sent, failed = 0, 0
    for uid in users:
        try:
            await bot.send_message(uid, body.message, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    return {"ok": True, "sent": sent, "failed": failed}

class CreatePromoRequest(BaseModel):
    code: str
    discount_rub: float
    uses: Optional[int] = None

@app.post("/api/admin/promo")
async def create_promo(body: CreatePromoRequest, user=Depends(require_owner)):
    await db.create_promo(body.code, body.discount_rub, body.uses)
    return {"ok": True}

@app.get("/api/admin/ref-tree/{admin_id}")
async def admin_ref_tree(admin_id: int, user=Depends(require_admin)):
    stats = await db.get_referral_stats(admin_id)
    return stats

@app.get("/health")
async def health():
    return {"status": "ok", "service": "LiliumVPN"}
