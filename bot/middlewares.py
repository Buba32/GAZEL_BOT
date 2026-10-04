from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.db import Database
from bot.keyboards import contact_kb

ASK_PHONE = (
    "Чтобы пользоваться ботом, поделитесь номером телефона — по нему с вами свяжется водитель. Нажмите кнопку ниже 👇"
)


class RegistrationMiddleware(BaseMiddleware):
    """Пропускает к хендлеру только тех, кто уже поделился номером. Кладёт строку пользователя в data["user"]."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db: Database = data["db"]
        tg_user = data.get("event_from_user")
        user = await db.get_user(tg_user.id) if tg_user else None
        if user is None:
            if isinstance(event, CallbackQuery):
                await event.answer("Сначала зарегистрируйтесь: /start", show_alert=True)
            elif isinstance(event, Message):
                await event.answer(ASK_PHONE, reply_markup=contact_kb())
            return None
        data["user"] = user
        return await handler(event, data)
