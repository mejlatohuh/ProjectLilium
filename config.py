import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8520036141:AAEBBQykxyyucFm3J-6c0XlY5lNeGqRgm_g")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # e.g. https://liliumvpn.onrender.com
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://yourusername.github.io/liliumvpn")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@ProjectLilium")
DATABASE_URL = os.getenv("DATABASE_URL", "")  # Supabase PostgreSQL URL

OWNER_ID = 1882575888
ADMIN_IDS = {
    1882575888: {"username": "adoqnc",   "code": "lilium", "name": "Mel"},
    1588480590: {"username": "drrhukl",  "code": "drr",    "name": "drrhukl"},
    1354912031: {"username": "tomdemisie","code": "tom",   "name": "Tom"},
    1730601024: {"username": "skinpish", "code": "skin",   "name": "skinpish"},
    1136404662: {"username": "mark",     "code": "mark",   "name": "Марк"},
}

PLANS = {
    "trial": {"name": "Пробный",    "days": 3,  "traffic_gb": 10, "price_stars": 0,   "price_rub": 0,   "devices": 1},
    "solo":  {"name": "SOLO",       "days": 30, "traffic_gb": 75, "price_stars": 75,  "price_rub": 89,  "devices": 1},
    "trio":  {"name": "TRIO",       "days": 30, "traffic_gb": 500,"price_stars": 180, "price_rub": 219, "devices": 3},
    "sentinel":{"name":"SENTINEL",  "days": 30, "traffic_gb": 1000,"price_stars":250, "price_rub": 299, "devices": 5},
    "immortal":{"name":"IMMORTAL",  "days": 30, "traffic_gb": -1, "price_stars": 450, "price_rub": 549, "devices": 10},
}

REFERRAL_REWARD_PERCENT = 25
REFERRAL_BONUS_NEW_USER = 50
REFERRAL_BONUS_INVITER = 50
MIN_WITHDRAWAL = 200

CKASSA_SHOP_ID = os.getenv("CKASSA_SHOP_ID", "")
CKASSA_SECRET = os.getenv("CKASSA_SECRET", "")
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "")
