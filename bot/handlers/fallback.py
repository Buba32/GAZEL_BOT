"""Всё, что не поймали остальные роутеры. Подключается последним."""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

from bot.db import Database
from bot.keyboards import contact_kb, main_menu_kb
from bot.middlewares import ASK_PHONE

router = Router(name="fallback")
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.message()
async def unknown_message(message: Message, db: Database) -> None:
    if await db.get_user(message.from_user.id) is None:
        await message.answer(ASK_PHONE, reply_markup=contact_kb())
    else:
        await message.answer("🤔 Не розумію. Оберіть дію в меню 👇", reply_markup=main_menu_kb())


@router.callback_query()
async def stale_button(callback: CallbackQuery) -> None:
    await callback.answer("Ця кнопка вже неактуальна")
