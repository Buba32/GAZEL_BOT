from collections.abc import Iterable

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

MENU_ORDER = "🚚 Заказать перевозку"
MENU_ADDRESSES = "📍 Мои адреса"
MENU_ORDERS = "📋 Мои заказы"
MENU_NEWS = "📰 Новости"
MENU_TARIFFS = "💰 Тарифы"

BTN_CONTACT = "📱 Поделиться номером"
BTN_LOCATION = "📍 Отправить геолокацию"
BTN_CANCEL = "❌ Отмена"


class AddressCb(CallbackData, prefix="addr"):
    id: int


class AddressDeleteCb(CallbackData, prefix="addr_del"):
    id: int


class OrderCb(CallbackData, prefix="order"):
    action: str  # confirm | restart | cancel


class AdminOrderCb(CallbackData, prefix="adm_order"):
    action: str  # accept | reject
    order_id: int


def _short(text: str, limit: int = 50) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_ORDER)],
            [KeyboardButton(text=MENU_ADDRESSES), KeyboardButton(text=MENU_ORDERS)],
            [KeyboardButton(text=MENU_NEWS), KeyboardButton(text=MENU_TARIFFS)],
        ],
        resize_keyboard=True,
    )


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CONTACT, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def address_input_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_LOCATION, request_location=True)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Город, улица, дом",
    )


def recent_addresses_kb(rows: Iterable) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.button(text=_short(row["address"]), callback_data=AddressCb(id=row["id"]))
    builder.adjust(1)
    return builder.as_markup()


def manage_addresses_kb(rows: Iterable) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.button(text=f"🗑 {_short(row['address'], 45)}", callback_data=AddressDeleteCb(id=row["id"]))
    builder.adjust(1)
    return builder.as_markup()


def confirm_order_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Оформить заказ", callback_data=OrderCb(action="confirm"))
    builder.button(text="🔄 Заново", callback_data=OrderCb(action="restart"))
    builder.button(text="❌ Отмена", callback_data=OrderCb(action="cancel"))
    builder.adjust(1, 2)
    return builder.as_markup()


def admin_order_kb(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=AdminOrderCb(action="accept", order_id=order_id))
    builder.button(text="❌ Отклонить", callback_data=AdminOrderCb(action="reject", order_id=order_id))
    return builder.as_markup()


def channel_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть канал", url=url)]])
