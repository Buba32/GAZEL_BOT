import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.config import Config
from bot.keyboards import admin_order_kb
from bot.services.geo import Place, Route
from bot.texts import fmt_km, fmt_price, map_url

log = logging.getLogger(__name__)


async def notify_new_order(
    bot: Bot, config: Config, order_id: int, user, src: Place, dst: Place, route: Route, price: int
) -> None:
    client = f'<a href="tg://user?id={user["tg_id"]}">{escape(user["first_name"] or "Клиент")}</a>'
    if user["username"]:
        client += f" (@{escape(user['username'])})"
    distance = fmt_km(route.distance_km) + (" (оценка по прямой)" if route.estimated else "")

    text = (
        f"🆕 <b>Заявка №{order_id}</b>\n\n"
        f"👤 {client}\n"
        f"📞 {escape(user['phone'])}\n\n"
        f"📍 Откуда: {escape(src.address)}\n"
        f"🏁 Куда: {escape(dst.address)}\n"
        f"🛣 {distance}\n"
        f"💰 {fmt_price(price)}\n"
        f'<a href="{map_url(src, dst)}">Маршрут на карте</a>'
    )

    chats = [config.admin_chat_id] if config.admin_chat_id else sorted(config.admin_ids)
    if not chats:
        log.warning("Order %s: ADMIN_CHAT_ID and ADMIN_IDS are empty, nobody to notify", order_id)
    for chat_id in chats:
        try:
            await bot.send_message(chat_id, text, reply_markup=admin_order_kb(order_id))
        except TelegramAPIError:
            # Чаще всего админ ещё не нажал /start у бота или бота нет в группе
            log.exception("Order %s: failed to notify chat %s", order_id, chat_id)
