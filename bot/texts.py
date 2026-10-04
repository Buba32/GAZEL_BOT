"""Форматирование сообщений. Всё, что пришло от пользователя или из карт, экранируется."""

from html import escape

from bot.db import ORDER_ACCEPTED, ORDER_NEW, ORDER_REJECTED
from bot.services.geo import Place, Route
from bot.services.pricing import Tariff

STATUS_LABELS = {
    ORDER_NEW: "🕐 Новая",
    ORDER_ACCEPTED: "✅ Принята",
    ORDER_REJECTED: "❌ Отклонена",
}


def fmt_price(uah: int | float) -> str:
    return f"{round(uah):,}".replace(",", " ") + " грн"


def fmt_km(km: float) -> str:
    return f"{km:.1f}".replace(".", ",") + " км"


def fmt_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{mins} мин"
    return f"{hours} ч {mins} мин" if mins else f"{hours} ч"


def map_url(src: Place, dst: Place) -> str:
    # Формат без «&» в query: ссылка переживает пересборку сообщения через Message.html_text,
    # которая не экранирует атрибуты, а голый «&» ломает HTML-разметку Telegram
    return f"https://www.google.com/maps/dir/{src.lat},{src.lon}/{dst.lat},{dst.lon}/"


def tariff_text(tariff: Tariff) -> str:
    return (
        "💰 <b>Тарифы</b>\n\n"
        f"Подача машины: {fmt_price(tariff.base_price)}\n"
        f"Километр пути: {fmt_price(tariff.price_per_km)}\n"
        f"Минимальный заказ: {fmt_price(tariff.min_price)}"
    )


def order_summary(src: Place, dst: Place, route: Route, price: int, tariff: Tariff) -> str:
    if route.estimated:
        distance = f"~{fmt_km(route.distance_km)} (приблизительно)"
    elif route.duration_min:
        distance = f"{fmt_km(route.distance_km)} (≈ {fmt_duration(route.duration_min)} в пути)"
    else:
        distance = fmt_km(route.distance_km)

    return (
        "🚚 <b>Расчёт перевозки</b>\n\n"
        f"📍 Откуда: {escape(src.address)}\n"
        f"🏁 Куда: {escape(dst.address)}\n"
        f"🛣 Расстояние: {distance}\n"
        f"💰 Стоимость: <b>{fmt_price(price)}</b>\n\n"
        f"<i>Подача {fmt_price(tariff.base_price)} + {fmt_price(tariff.price_per_km)}/км, "
        f"минимум {fmt_price(tariff.min_price)}</i>\n"
        f'<a href="{map_url(src, dst)}">Маршрут на карте</a>'
    )
