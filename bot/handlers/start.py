from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db import Database
from bot.keyboards import contact_kb, main_menu_kb

router = Router(name="start")
router.message.filter(F.chat.type == ChatType.PRIVATE)

WELCOME = (
    "👋 Здравствуйте! Это бот грузоперевозок на Газели по Харькову и Харьковской области.\n\n"
    "Здесь можно за минуту рассчитать стоимость перевозки по адресам и оформить заказ.\n\n"
    "Для начала поделитесь номером телефона — по нему с вами свяжется водитель 👇"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if user is None:
        await message.answer(WELCOME, reply_markup=contact_kb())
        return
    name = escape(user["first_name"] or "")
    await message.answer(
        f"С возвращением{', ' + name if name else ''}! Выберите действие 👇", reply_markup=main_menu_kb()
    )


@router.message(F.contact)
async def on_contact(message: Message, db: Database) -> None:
    contact = message.contact
    # Принимаем только собственный контакт, а не пересланный чужой
    if contact.user_id != message.from_user.id:
        await message.answer("Пожалуйста, отправьте <b>свой</b> номер — кнопкой ниже.", reply_markup=contact_kb())
        return

    phone = contact.phone_number if contact.phone_number.startswith("+") else f"+{contact.phone_number}"
    await db.upsert_user(message.from_user.id, phone, message.from_user.first_name, message.from_user.username)
    await message.answer(
        f"✅ Готово! Ваш номер <b>{escape(phone)}</b> сохранён.\n\nТеперь можно заказать перевозку 👇",
        reply_markup=main_menu_kb(),
    )
