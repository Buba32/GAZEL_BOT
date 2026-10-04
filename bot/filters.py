from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from bot.config import Config


class IsAdmin(Filter):
    async def __call__(self, event: Message | CallbackQuery, config: Config) -> bool:
        return event.from_user is not None and event.from_user.id in config.admin_ids
