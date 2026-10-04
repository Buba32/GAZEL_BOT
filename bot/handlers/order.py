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
    "📍 <b>Звідки</b> забрати вантаж?\n\n"
    "Напишіть адресу (вулиця, будинок; для області — ще й населений пункт) або надішліть геолокацію.\n"
    "Можна українською або російською."
)
DST_PROMPT = "🏁 <b>Куди</b> веземо?\n\nНапишіть адресу або надішліть геолокацію."
NOT_FOUND = (
    "😕 Не вдалося знайти таку адресу в Харкові та області. Напишіть детальніше: вулиця й будинок — "
    "наприклад, <i>Сумська 10</i> або <i>Чугуїв, Харківська 5</i>. Або надішліть геолокацію."
)
GEO_DOWN = "⚠️ Сервіс карт зараз не відповідає. Спробуйте ще раз за хвилину або надішліть геолокацію."

# Ближе 50 м считаем, что это одна и та же точка
SAME_PLACE_KM = 0.05


async def ask_address(message: Message, user_id: int, db: Database, prompt: str) -> None:
    await message.answer(prompt, reply_markup=address_input_kb())
    recent = await db.recent_addresses(user_id)
    if recent:
        await message.answer("Або оберіть із нещодавніх:", reply_markup=recent_addresses_kb(recent))


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
    await message.answer("Замовлення скасовано.", reply_markup=main_menu_kb())


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
        await callback.answer("Адресу не знайдено — можливо, ви її видалили", show_alert=True)
        return
    await callback.answer()
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await accept_place(callback.message, callback.from_user.id, place, state, db, geo, config)


@router.message(StateFilter(OrderForm.src, OrderForm.dst))
async def address_unsupported(message: Message) -> None:
    await message.answer("Надішліть адресу текстом або геолокацію 📍")


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
        await message.answer(f"📍 Звідки: <b>{escape(place.address)}</b>")
        await ask_address(message, user_id, db, DST_PROMPT)
        return

    src = Place(**(await state.get_data())["src"])
    if haversine_km(src, place) < SAME_PLACE_KM:
        await message.answer("Адреса призначення збігається з адресою відправлення. Вкажіть іншу адресу.")
        return

    await message.answer(f"🏁 Куди: <b>{escape(place.address)}</b>\n\n⏳ Рахую маршрут…", reply_markup=main_menu_kb())
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
        order_summary(src, dst, route, price, config.tariff) + f"\n\n✅ <b>Заявку №{order_id} оформлено!</b>\n"
        f"Менеджер зв'яжеться з вами за номером {escape(user['phone'])}.",
        reply_markup=None,
    )
    await callback.answer("Заявку надіслано")
    await notify_new_order(bot, config, order_id, user, src, dst, route, price)


@router.callback_query(OrderForm.confirm, OrderCb.filter(F.action == "restart"))
async def restart_order(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await begin_order(callback.message, callback.from_user.id, state, db)


@router.callback_query(OrderForm.confirm, OrderCb.filter(F.action == "cancel"))
async def cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Замовлення скасовано")
    await callback.message.edit_reply_markup(reply_markup=None)
