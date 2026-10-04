from datetime import datetime
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import Database
from bot.keyboards import (
    MENU_ADDRESSES,
    MENU_NEWS,
    MENU_ORDERS,
    MENU_TARIFFS,
    AddressDeleteCb,
    channel_kb,
    manage_addresses_kb,
)
from bot.middlewares import RegistrationMiddleware
from bot.texts import STATUS_LABELS, fmt_km, fmt_price, tariff_text

router = Router(name="menu")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
router.message.middleware(RegistrationMiddleware())
router.callback_query.middleware(RegistrationMiddleware())

ADDRESSES_HINT = (
    "📍 <b>Ваші адреси</b>\n\nВони підставляються під час оформлення замовлення. Натисніть на адресу, щоб видалити її."
)
NO_ADDRESSES = "Збережених адрес поки немає — вони з'являться після першого замовлення."


@router.message(F.text == MENU_NEWS)
async def news(message: Message, config: Config) -> None:
    if config.channel_url:
        await message.answer(
            "📰 Новини, акції та корисне — у нашому каналі:", reply_markup=channel_kb(config.channel_url)
        )
    else:
        await message.answer("📰 Канал із новинами скоро з'явиться.")


@router.message(F.text == MENU_TARIFFS)
async def tariffs(message: Message, config: Config) -> None:
    await message.answer(tariff_text(config.tariff))


@router.message(F.text == MENU_ORDERS)
async def my_orders(message: Message, db: Database) -> None:
    rows = await db.user_orders(message.from_user.id)
    if not rows:
        await message.answer("У вас поки немає замовлень. Натисніть «🚚 Замовити перевезення».")
        return

    lines = ["📋 <b>Ваші замовлення</b>"]
    for r in rows:
        date = datetime.fromisoformat(r["created_at"]).strftime("%d.%m.%Y")
        lines.append(
            f"\n<b>№{r['id']}</b> · {date} · {STATUS_LABELS.get(r['status'], r['status'])}\n"
            f"{escape(r['from_address'])} → {escape(r['to_address'])}\n"
            f"{fmt_km(r['distance_km'])} · {fmt_price(r['price'])}"
        )
    await message.answer("\n".join(lines))


@router.message(F.text == MENU_ADDRESSES)
async def my_addresses(message: Message, db: Database) -> None:
    rows = await db.recent_addresses(message.from_user.id, limit=10)
    if not rows:
        await message.answer(NO_ADDRESSES)
        return
    await message.answer(ADDRESSES_HINT, reply_markup=manage_addresses_kb(rows))


@router.callback_query(AddressDeleteCb.filter())
async def delete_address(callback: CallbackQuery, callback_data: AddressDeleteCb, db: Database) -> None:
    await db.delete_address(callback_data.id, callback.from_user.id)
    rows = await db.recent_addresses(callback.from_user.id, limit=10)
    if rows:
        await callback.message.edit_reply_markup(reply_markup=manage_addresses_kb(rows))
    else:
        await callback.message.edit_text(NO_ADDRESSES)
    await callback.answer("Адресу видалено")
