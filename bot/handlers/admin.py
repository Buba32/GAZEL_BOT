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
    "Как опубликовать новость в канал:\n\n"
    "• <code>/post Текст новости</code> — простой текст (можно HTML-теги &lt;b&gt;, &lt;i&gt;);\n"
    "• или подготовьте пост (текст, фото, видео) и ответьте на него командой <code>/post</code> — "
    "он уйдёт в канал как есть, с форматированием."
)


@router.message(Command("post"), IsAdmin())
async def post_to_channel(message: Message, command: CommandObject, bot: Bot, config: Config) -> None:
    if not config.channel_id:
        await message.answer("Канал не настроен: задайте CHANNEL_ID в .env")
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
            f"❌ Не удалось опубликовать: {escape(str(e))}\n\nПроверьте, что бот добавлен в канал администратором."
        )
        return
    await message.answer("✅ Опубликовано в канале")


@router.callback_query(AdminOrderCb.filter(), IsAdmin())
async def process_order(callback: CallbackQuery, callback_data: AdminOrderCb, db: Database, bot: Bot) -> None:
    accepted = callback_data.action == "accept"
    status = ORDER_ACCEPTED if accepted else ORDER_REJECTED
    order_id = callback_data.order_id

    if not await db.set_order_status(order_id, status):
        await callback.answer("Заявка уже обработана", show_alert=True)
        return

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"{callback.message.html_text}\n\n<b>{STATUS_LABELS[status]}</b> — {escape(callback.from_user.full_name)}",
            reply_markup=None,
        )
    await callback.answer(STATUS_LABELS[status])

    order = await db.get_order(order_id)
    text = (
        f"✅ Ваша заявка №{order_id} принята! Водитель свяжется с вами в ближайшее время."
        if accepted
        else f"😔 К сожалению, заявка №{order_id} отклонена. Свяжитесь с нами или оформите новую."
    )
    try:
        await bot.send_message(order["user_id"], text)
    except TelegramAPIError:
        log.warning("Order %s: failed to notify client %s", order_id, order["user_id"], exc_info=True)


@router.callback_query(AdminOrderCb.filter())
async def process_order_forbidden(callback: CallbackQuery) -> None:
    await callback.answer("Только для администраторов", show_alert=True)
