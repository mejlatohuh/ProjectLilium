import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice,
    PreCheckoutQuery, Message, CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
import json

from config import (BOT_TOKEN, WEBHOOK_URL, WEBAPP_URL, CHANNEL_ID,
                    ADMIN_IDS, OWNER_ID, PLANS)
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# ─── States ──────────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    broadcast = State()
    give_balance_id = State()
    give_balance_amount = State()
    create_promo = State()

# ─── Helpers ─────────────────────────────────────────────────────────────────

async def check_channel_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ["left", "kicked", "banned"]
    except Exception:
        return False

def make_channel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
    ])

def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    webapp_url = WEBAPP_URL
    is_admin = user_id in ADMIN_IDS

    builder = InlineKeyboardBuilder()
    builder.button(text="🌸 Открыть LiliumVPN", web_app=WebAppInfo(url=webapp_url))
    builder.button(text="📋 Мой профиль", callback_data="profile")
    builder.button(text="🔑 Моя подписка", callback_data="subscription")
    builder.button(text="👥 Рефералы", callback_data="referrals")
    builder.button(text="💳 Купить подписку", callback_data="buy")
    builder.button(text="🆘 Поддержка", url=f"https://t.me/ProjectLilium")
    if is_admin:
        builder.button(text="⚙️ Панель администратора", callback_data="admin_panel")
    builder.adjust(1)
    return builder.as_markup()

# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
    ref_code = args.replace("ref_", "") if args and args.startswith("ref_") else args

    user_data, is_new = await db.get_or_create_user(
        tg_id=user.id,
        username=user.username,
        first_name=user.first_name,
        ref_code=ref_code
    )

    subscribed = await check_channel_subscription(user.id)
    await db.set_channel_subscribed(user.id, subscribed)

    if not subscribed:
        await message.answer(
            "🌸 *Добро пожаловать в LiliumVPN!*\n\n"
            "Для использования сервиса необходимо подписаться на наш канал.",
            parse_mode="Markdown",
            reply_markup=make_channel_kb()
        )
        return

    if is_new and ref_code:
        await db.add_balance(user.id, 50)  # Bonus for new user
        await message.answer(
            "🎁 На твой баланс начислено *+50 ₽* за переход по реферальной ссылке!",
            parse_mode="Markdown"
        )

    greeting = "🌸 *LiliumVPN* — твой приватный интернет\n\n"
    if is_new:
        greeting += "Активируй *бесплатный пробный период* прямо сейчас!\n\n"
    else:
        sub = await db.get_active_subscription(user.id)
        if sub:
            import datetime
            days_left = (sub["end_date"] - datetime.datetime.utcnow()).days
            greeting += f"📡 Тариф: *{sub['plan'].upper()}* · Осталось: *{days_left} дн.*\n\n"
        else:
            greeting += "⚠️ У тебя нет активной подписки.\n\n"

    greeting += "Выбери действие:"
    await message.answer(greeting, parse_mode="Markdown", reply_markup=main_menu_kb(user.id))

# ─── Channel check callback ───────────────────────────────────────────────────

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    subscribed = await check_channel_subscription(call.from_user.id)
    if subscribed:
        await db.set_channel_subscribed(call.from_user.id, True)
        await call.message.edit_text(
            "✅ Отлично! Добро пожаловать в *LiliumVPN!*",
            parse_mode="Markdown"
        )
        await call.message.answer(
            "Выбери действие:",
            reply_markup=main_menu_kb(call.from_user.id)
        )
    else:
        await call.answer("Ты ещё не подписался! Подпишись и нажми снова.", show_alert=True)

# ─── Profile ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "profile")
async def show_profile(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    if not user:
        await call.answer("Пользователь не найден")
        return
    text = (
        f"👤 *Профиль*\n\n"
        f"🆔 Telegram ID: `{user['telegram_id']}`\n"
        f"👤 Username: @{user['username'] or '—'}\n"
        f"🏷 Код реферала: `{user['ref_code']}`\n"
        f"💰 Баланс: *{user['balance']} ₽*\n"
        f"📅 Дата регистрации: {user['created_at'].strftime('%d.%m.%Y') if user['created_at'] else '—'}\n"
        f"🎭 Роль: {user['role']}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

# ─── Subscription ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "subscription")
async def show_subscription(call: CallbackQuery):
    sub = await db.get_active_subscription(call.from_user.id)
    if not sub:
        text = "❌ У тебя нет активной подписки."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
        ])
    else:
        import datetime
        days_left = max(0, (sub["end_date"] - datetime.datetime.utcnow()).days)
        used_mb = sub["traffic_used_mb"]
        limit_mb = sub["traffic_limit_mb"]
        if limit_mb == -1:
            traffic_str = f"{used_mb} MB / ∞"
        else:
            limit_gb = limit_mb / 1024
            used_gb = round(used_mb / 1024, 2)
            traffic_str = f"{used_gb} GB / {limit_gb:.0f} GB"
        text = (
            f"📡 *Твоя подписка*\n\n"
            f"📦 Тариф: *{sub['plan'].upper()}*\n"
            f"📅 Действует до: {sub['end_date'].strftime('%d.%m.%Y')}\n"
            f"⏳ Осталось: *{days_left} дн.*\n"
            f"📊 Трафик: {traffic_str}\n"
            f"🖥 Устройств: {sub['devices']}\n\n"
        )
        if sub.get("vpn_key"):
            text += f"🔑 Ключ подписки:\n`{sub['vpn_key']}`"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Продлить", callback_data="buy")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
        ])
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

# ─── Buy / Plans ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "buy")
async def show_plans(call: CallbackQuery):
    builder = InlineKeyboardBuilder()
    for key, plan in PLANS.items():
        if key == "trial":
            continue
        builder.button(
            text=f"{plan['name']} — {plan['price_rub']}₽/мес ({plan['price_stars']}⭐)",
            callback_data=f"plan_{key}"
        )
    builder.button(text="🎁 Пробный 3 дня (бесплатно)", callback_data="plan_trial")
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    await call.message.edit_text(
        "💳 *Выбери тариф:*\n\nОплата: ⭐ Telegram Stars · Crypto · CKassa",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("plan_"))
async def select_plan(call: CallbackQuery):
    plan_key = call.data.replace("plan_", "")
    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Тариф не найден")
        return

    if plan_key == "trial":
        existing = await db.get_active_subscription(call.from_user.id)
        if existing:
            await call.answer("У тебя уже есть активная подписка!", show_alert=True)
            return
        sub = await db.create_subscription(call.from_user.id, "trial")
        await call.message.edit_text(
            f"✅ Пробный период активирован!\n\n"
            f"⏳ 3 дня · 10 ГБ · 1 устройство\n\n"
            f"Открой личный кабинет для получения ключа.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🌸 Открыть кабинет", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
            ])
        )
        return

    builder = InlineKeyboardBuilder()
    builder.button(text=f"⭐ Оплатить {plan['price_stars']} Stars", callback_data=f"pay_stars_{plan_key}")
    builder.button(text="🪙 Оплатить криптой", callback_data=f"pay_crypto_{plan_key}")
    builder.button(text="💳 Оплатить CKassa", callback_data=f"pay_ckassa_{plan_key}")
    builder.button(text="💰 Оплатить с баланса", callback_data=f"pay_balance_{plan_key}")
    builder.button(text="◀️ Назад", callback_data="buy")
    builder.adjust(1)

    # Исправлено: вынесли сложное выражение в переменную
    traffic_text = 'Безлимит' if plan['traffic_gb'] == -1 else f"{plan['traffic_gb']} ГБ/мес"

    await call.message.edit_text(
        f"📦 *{plan['name']}*\n\n"
        f"📊 Трафик: {traffic_text}\n"
        f"🖥 Устройств: {plan['devices']}\n"
        f"📅 Срок: {plan['days']} дней\n\n"
        f"Выбери способ оплаты:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

# ─── Payment — Telegram Stars ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_stars_"))
async def pay_stars(call: CallbackQuery):
    plan_key = call.data.replace("pay_stars_", "")
    plan = PLANS.get(plan_key)
    if not plan:
        return
    
    # Исправлено: вынесли сложное выражение в переменную
    traffic_short = 'Безлимит' if plan['traffic_gb'] == -1 else f"{plan['traffic_gb']} ГБ"
    
    await call.message.answer_invoice(
        title=f"LiliumVPN — {plan['name']}",
        description=f"{plan['days']} дней · {traffic_short} · {plan['devices']} уст.",
        payload=f"vpn_{plan_key}_{call.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label=plan["name"], amount=plan["price_stars"])],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ Оплатить {plan['price_stars']} Stars", pay=True)],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"plan_{plan_key}")]
        ])
    )

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    plan_key = parts[1]
    user_id = int(parts[2])
    amount_stars = message.successful_payment.total_amount

    payment = await db.create_payment(user_id, amount_stars, "stars", plan_key, payload)
    await db.confirm_payment(payment["id"])
    sub = await db.create_subscription(user_id, plan_key)
    await db.process_referral_reward(user_id, PLANS[plan_key]["price_rub"], "stars")

    await message.answer(
        f"✅ *Оплата прошла успешно!*\n\n"
        f"📦 Тариф *{PLANS[plan_key]['name']}* активирован.\n"
        f"Открой личный кабинет для получения ключа подписки.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌸 Открыть кабинет", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
    )

# ─── Payment — Balance ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_balance_"))
async def pay_balance(call: CallbackQuery):
    plan_key = call.data.replace("pay_balance_", "")
    plan = PLANS.get(plan_key)
    user = await db.get_user(call.from_user.id)
    price = plan["price_rub"]

    if user["balance"] < price:
        await call.answer(f"Недостаточно средств. На балансе {user['balance']} ₽, нужно {price} ₽", show_alert=True)
        return

    p = await db.get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE users SET balance=balance-$1 WHERE telegram_id=$2", price, call.from_user.id)

    payment = await db.create_payment(call.from_user.id, price, "balance", plan_key)
    await db.confirm_payment(payment["id"])
    sub = await db.create_subscription(call.from_user.id, plan_key)
    await db.process_referral_reward(call.from_user.id, price, "balance")

    await call.message.edit_text(
        f"✅ Тариф *{plan['name']}* активирован!\nСписано *{price} ₽* с баланса.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌸 Открыть кабинет", web_app=WebAppInfo(url=WEBAPP_URL))],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
        ])
    )

# ─── Payment — Crypto (CryptoBot) ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_crypto_"))
async def pay_crypto(call: CallbackQuery):
    plan_key = call.data.replace("pay_crypto_", "")
    plan = PLANS.get(plan_key)
    usdt_price = round(plan["price_rub"] / 90, 2)
    await call.message.edit_text(
        f"🪙 *Оплата криптовалютой*\n\n"
        f"Тариф: *{plan['name']}*\n"
        f"Сумма: *{usdt_price} USDT*\n\n"
        f"Отправь платёж через @CryptoBot:\n"
        f"Нажми кнопку ниже и следуй инструкциям.\n\n"
        f"После оплаты напиши в поддержку с чеком.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Оплатить через CryptoBot",
                url=f"https://t.me/CryptoBot?start=invoice")],
            [InlineKeyboardButton(text="📩 Написать в поддержку",
                url="https://t.me/ProjectLilium")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"plan_{plan_key}")]
        ])
    )

# ─── Referrals ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "referrals")
async def show_referrals(call: CallbackQuery):
    stats = await db.get_referral_stats(call.from_user.id)
    code = stats.get("ref_code", "—")
    bot_link = f"https://t.me/LiliumVPNBot?start=ref_{code}"
    cabinet_link = f"{WEBAPP_URL}?ref={code}"

    text = (
        f"👥 *Реферальная программа*\n\n"
        f"🏷 Твой код: `{code}`\n"
        f"👫 Всего рефералов: *{stats.get('total', 0)}*\n"
        f"💰 Заработано: *+{stats.get('earned', 0):.2f} ₽*\n\n"
        f"📎 Ссылка на бота:\n`{bot_link}`\n\n"
        f"📎 Ссылка на кабинет:\n`{cabinet_link}`\n\n"
        f"_Ты получаешь 25% с каждой оплаты реферала_"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Поделиться ссылкой", url=f"https://t.me/share/url?url={bot_link}&text=Попробуй%20LiliumVPN!")
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())

# ─── Back ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back_main")
async def back_main(call: CallbackQuery):
    await call.message.edit_text("Выбери действие:", reply_markup=main_menu_kb(call.from_user.id))

# ─── Admin Panel ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Нет доступа", show_alert=True)
        return

    is_owner = call.from_user.id == OWNER_ID
    stats = await db.get_admin_stats()
    text = (
        f"⚙️ *Панель администратора*\n\n"
        f"👥 Всего пользователей: *{stats['total_users']}*\n"
        f"📡 Активных подписок: *{stats['active_subs']}*\n"
        f"💰 Доход сегодня: *{stats['revenue_today']} ₽*\n"
        f"📈 Доход за месяц: *{stats['revenue_month']} ₽*\n"
        f"🆕 Новых сегодня: *{stats['new_today']}*"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Список пользователей", callback_data="admin_users")
    builder.button(text="👥 Рефералы (дерево)", callback_data="admin_ref_tree")
    if is_owner:
        builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
        builder.button(text="💰 Начислить баланс", callback_data="admin_give_balance")
        builder.button(text="🎟 Создать промокод", callback_data="admin_promo")
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    users = await db.get_all_users_paginated(0, 30)
    lines = []
    for u in users[:30]:
        uname = f"@{u['username']}" if u["username"] else u["first_name"] or "—"
        lines.append(f"• {uname} `{u['telegram_id']}` [{u['role']}] {u['balance']}₽")
    text = "👥 *Пользователи* (30 последних):\n\n" + "\n".join(lines)
    await call.message.edit_text(text[:4000], parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ]))

@router.callback_query(F.data == "admin_ref_tree")
async def admin_ref_tree(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    stats = await db.get_referral_stats(call.from_user.id)
    refs = stats.get("referrals", [])
    lines = [f"🌸 *Твоё реферальное дерево* ({stats.get('total', 0)} чел.)\n"]
    for r in refs[:20]:
        uname = f"@{r['username']}" if r["username"] else r["first_name"] or "—"
        lines.append(f"└ {uname} · код: `{r['ref_code']}` · {'✅ sub' if r['has_sub'] else '❌ no sub'}")
    await call.message.edit_text("\n".join(lines) or "Рефералов пока нет.", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ]))

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await call.message.edit_text("📢 Введи текст рассылки (поддерживается Markdown):")
    await state.set_state(AdminStates.broadcast)

@router.message(AdminStates.broadcast)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    await state.clear()
    users = await db.admin_broadcast_get_users()
    sent, failed = 0, 0
    for uid in users:
        try:
            await bot.send_message(uid, message.text, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await message.answer(f"✅ Рассылка завершена: {sent} отправлено, {failed} ошибок.")

@router.callback_query(F.data == "admin_give_balance")
async def admin_give_balance_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await call.message.edit_text("💰 Введи Telegram ID пользователя:")
    await state.set_state(AdminStates.give_balance_id)

@router.message(AdminStates.give_balance_id)
async def admin_give_balance_id(message: Message, state: FSMContext):
    await state.update_data(target_id=int(message.text.strip()))
    await message.answer("Введи сумму (в рублях):")
    await state.set_state(AdminStates.give_balance_amount)

@router.message(AdminStates.give_balance_amount)
async def admin_give_balance_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = float(message.text.strip())
    await db.admin_give_balance(data["target_id"], amount)
    await state.clear()
    await message.answer(f"✅ Начислено {amount} ₽ пользователю {data['target_id']}")

@router.callback_query(F.data == "admin_promo")
async def admin_promo(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await call.message.edit_text("🎟 Введи данные промокода в формате:\n`КОД СУММА_РУБ КОЛИЧЕСТВО_ИСПОЛЬЗОВАНИЙ`\nПример: `LILIUM50 50 100`")
    await state.set_state(AdminStates.create_promo)

@router.message(AdminStates.create_promo)
async def do_create_promo(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Неверный формат")
        return
    code = parts[0]
    amount = float(parts[1])
    uses = int(parts[2]) if len(parts) > 2 else None
    await db.create_promo(code, amount, uses)
    await state.clear()
    await message.answer(f"✅ Промокод `{code}` создан: +{amount}₽, использований: {uses or '∞'}", parse_mode="Markdown")

# ─── Main ─────────────────────────────────────────────────────────────────────

dp.include_router(router)

async def main():
    await db.init_db()
    if WEBHOOK_URL:
        await bot.set_webhook(f"{WEBHOOK_URL}/webhook")
        logger.info(f"Webhook set to {WEBHOOK_URL}/webhook")
    else:
        await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
