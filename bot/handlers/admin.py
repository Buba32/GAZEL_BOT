import logging
from html import escape

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import ORDER_ACCEPTED, ORDER_REJECTED, Database
from bot.filters import IsAdmin
from bot.keyboards import AdminOrderCb
from bot.texts import STATUS_LABELS

log = logging.getLogger(__name__)

router = Router(name="admin")

POST_USAGE = (
    "Як опублікувати новину в канал:\n\n"
    "• <code>/post Текст новини</code> — простий текст (можна HTML-теги &lt;b&gt;, &lt;i&gt;);\n"
    "• або підготуйте пост (текст, фото, відео) і дайте відповідь на нього командою <code>/post</code> — "
    "він піде в канал як є, з форматуванням."
)


@router.message(Command("post"), IsAdmin())
async def post_to_channel(message: Message, command: CommandObject, bot: Bot, config: Config) -> None:
    if not config.channel_id:
        await message.answer("Канал не налаштовано: вкажіть CHANNEL_ID у .env")
        return
    try:
        if message.reply_to_message:
            await bot.copy_message(config.channel_id, message.chat.id, message.reply_to_message.message_id)
        elif command.args:
            await bot.send_message(config.channel_id, command.args)
        else:
            await message.answer(POST_USAGE)
            return
    except TelegramAPIError as e:
        await message.answer(
            f"❌ Не вдалося опублікувати: {escape(str(e))}\n\nПеревірте, що бота додано в канал адміністратором."
        )
        return
    await message.answer("✅ Опубліковано в каналі")


@router.callback_query(AdminOrderCb.filter(), IsAdmin())
async def process_order(callback: CallbackQuery, callback_data: AdminOrderCb, db: Database, bot: Bot) -> None:
    accepted = callback_data.action == "accept"
    status = ORDER_ACCEPTED if accepted else ORDER_REJECTED
    order_id = callback_data.order_id

    if not await db.set_order_status(order_id, status):
        await callback.answer("Заявку вже оброблено", show_alert=True)
        return

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"{callback.message.html_text}\n\n<b>{STATUS_LABELS[status]}</b> — {escape(callback.from_user.full_name)}",
            reply_markup=None,
        )
    await callback.answer(STATUS_LABELS[status])

    order = await db.get_order(order_id)
    text = (
        f"✅ Вашу заявку №{order_id} прийнято! Водій зв'яжеться з вами найближчим часом."
        if accepted
        else f"😔 На жаль, заявку №{order_id} відхилено. Зв'яжіться з нами або оформіть нову."
    )
    try:
        await bot.send_message(order["user_id"], text)
    except TelegramAPIError:
        log.warning("Order %s: failed to notify client %s", order_id, order["user_id"], exc_info=True)


@router.callback_query(AdminOrderCb.filter())
async def process_order_forbidden(callback: CallbackQuery) -> None:
    await callback.answer("Лише для адміністраторів", show_alert=True)
