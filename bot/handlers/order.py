from contextlib import suppress
from dataclasses import asdict
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import Database
from bot.keyboards import (
    BTN_CANCEL,
    MENU_ORDER,
    AddressCb,
    OrderCb,
    address_input_kb,
    confirm_order_kb,
    main_menu_kb,
    recent_addresses_kb,
)
from bot.middlewares import RegistrationMiddleware
from bot.services.geo import GeoError, GeoService, Place, Route, haversine_km
from bot.services.notify import notify_new_order
from bot.services.pricing import calc_price
from bot.states import OrderForm
from bot.texts import order_summary

router = Router(name="order")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
router.message.middleware(RegistrationMiddleware())
router.callback_query.middleware(RegistrationMiddleware())

SRC_PROMPT = (
    "📍 <b>Откуда</b> забрать груз?\n\n"
    "Напишите адрес (улица, дом; для области — ещё и населённый пункт) или отправьте геолокацию."
)
DST_PROMPT = "🏁 <b>Куда</b> везём?\n\nНапишите адрес или отправьте геолокацию."
NOT_FOUND = (
    "😕 Не нашёл такой адрес в Харькове и области. Напишите подробнее: улица и дом — "
    "например, <i>Сумская 10</i> или <i>Чугуев, Харьковская 5</i>. Или отправьте геолокацию."
)
GEO_DOWN = "⚠️ Сервис карт сейчас не отвечает. Попробуйте ещё раз через минуту или отправьте геолокацию."

# Ближе 50 м считаем, что это одна и та же точка
SAME_PLACE_KM = 0.05


async def ask_address(message: Message, user_id: int, db: Database, prompt: str) -> None:
    await message.answer(prompt, reply_markup=address_input_kb())
    recent = await db.recent_addresses(user_id)
    if recent:
        await message.answer("Или выберите из недавних:", reply_markup=recent_addresses_kb(recent))


async def begin_order(message: Message, user_id: int, state: FSMContext, db: Database) -> None:
    await state.clear()
    await state.set_state(OrderForm.src)
    await ask_address(message, user_id, db, SRC_PROMPT)


@router.message(F.text == MENU_ORDER)
async def start_order(message: Message, state: FSMContext, db: Database) -> None:
    await begin_order(message, message.from_user.id, state, db)


@router.message(F.text == BTN_CANCEL)
@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Заказ отменён.", reply_markup=main_menu_kb())


# --- Ввод адресов: текстом, геолокацией или из недавних ---


@router.message(StateFilter(OrderForm.src, OrderForm.dst), F.text)
async def address_text(message: Message, state: FSMContext, db: Database, geo: GeoService, config: Config) -> None:
    try:
        place = await geo.geocode(message.text.strip())
    except GeoError:
        await message.answer(GEO_DOWN)
        return
    if place is None:
        await message.answer(NOT_FOUND)
        return
    await accept_place(message, message.from_user.id, place, state, db, geo, config)


@router.message(StateFilter(OrderForm.src, OrderForm.dst), F.location)
async def address_location(message: Message, state: FSMContext, db: Database, geo: GeoService, config: Config) -> None:
    place = await geo.reverse(message.location.latitude, message.location.longitude)
    await accept_place(message, message.from_user.id, place, state, db, geo, config)


@router.callback_query(StateFilter(OrderForm.src, OrderForm.dst), AddressCb.filter())
async def address_recent(
    callback: CallbackQuery,
    callback_data: AddressCb,
    state: FSMContext,
    db: Database,
    geo: GeoService,
    config: Config,
) -> None:
    place = await db.get_address(callback_data.id, callback.from_user.id)
    if place is None:
        await callback.answer("Адрес не найден — возможно, вы его удалили", show_alert=True)
        return
    await callback.answer()
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await accept_place(callback.message, callback.from_user.id, place, state, db, geo, config)


@router.message(StateFilter(OrderForm.src, OrderForm.dst))
async def address_unsupported(message: Message) -> None:
    await message.answer("Отправьте адрес текстом или геолокацию 📍")


async def accept_place(
    message: Message,
    user_id: int,
    place: Place,
    state: FSMContext,
    db: Database,
    geo: GeoService,
    config: Config,
) -> None:
    if await state.get_state() == OrderForm.src.state:
        await state.update_data(src=asdict(place))
        await state.set_state(OrderForm.dst)
        await message.answer(f"📍 Откуда: <b>{escape(place.address)}</b>")
        await ask_address(message, user_id, db, DST_PROMPT)
        return

    src = Place(**(await state.get_data())["src"])
    if haversine_km(src, place) < SAME_PLACE_KM:
        await message.answer("Адрес назначения совпадает с адресом отправления. Укажите другой адрес.")
        return

    await message.answer(f"🏁 Куда: <b>{escape(place.address)}</b>\n\n⏳ Считаю маршрут…", reply_markup=main_menu_kb())
    route = await geo.route(src, place)
    price = calc_price(route.distance_km, config.tariff)
    await state.update_data(dst=asdict(place), route=asdict(route), price=price)
    await state.set_state(OrderForm.confirm)
    await message.answer(order_summary(src, place, route, price, config.tariff), reply_markup=confirm_order_kb())


# --- Подтверждение ---


@router.callback_query(OrderForm.confirm, OrderCb.filter(F.action == "confirm"))
async def confirm_order(
    callback: CallbackQuery, state: FSMContext, db: Database, bot: Bot, config: Config, user
) -> None:
    data = await state.get_data()
    await state.clear()
    if "dst" not in data:
        # Двойное нажатие: первое уже оформило заявку и очистило состояние
        await callback.answer()
        return

    src, dst, route, price = Place(**data["src"]), Place(**data["dst"]), Route(**data["route"]), data["price"]
    order_id = await db.create_order(user["tg_id"], src, dst, route.distance_km, price)
    await db.save_address(user["tg_id"], src)
    await db.save_address(user["tg_id"], dst)

    await callback.message.edit_text(
        order_summary(src, dst, route, price, config.tariff) + f"\n\n✅ <b>Заявка №{order_id} оформлена!</b>\n"
        f"Менеджер свяжется с вами по номеру {escape(user['phone'])}.",
        reply_markup=None,
    )
    await callback.answer("Заявка отправлена")
    await notify_new_order(bot, config, order_id, user, src, dst, route, price)


@router.callback_query(OrderForm.confirm, OrderCb.filter(F.action == "restart"))
async def restart_order(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await begin_order(callback.message, callback.from_user.id, state, db)


@router.callback_query(OrderForm.confirm, OrderCb.filter(F.action == "cancel"))
async def cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Заказ отменён")
    await callback.message.edit_reply_markup(reply_markup=None)
