"""Форматирование сообщений. Всё, что пришло от пользователя или из карт, экранируется."""

from html import escape

from bot.db import ORDER_ACCEPTED, ORDER_NEW, ORDER_REJECTED
from bot.services.geo import Place, Route
from bot.services.pricing import Tariff

STATUS_LABELS = {
    ORDER_NEW: "🕐 Нова",
    ORDER_ACCEPTED: "✅ Прийнята",
    ORDER_REJECTED: "❌ Відхилена",
}


def fmt_price(uah: int | float) -> str:
    return f"{round(uah):,}".replace(",", " ") + " грн"


def fmt_km(km: float) -> str:
    return f"{km:.1f}".replace(".", ",") + " км"


def fmt_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{mins} хв"
    return f"{hours} год {mins} хв" if mins else f"{hours} год"


def map_url(src: Place, dst: Place) -> str:
    # Формат без «&» в query: ссылка переживает пересборку сообщения через Message.html_text,
    # которая не экранирует атрибуты, а голый «&» ломает HTML-разметку Telegram
    return f"https://www.google.com/maps/dir/{src.lat},{src.lon}/{dst.lat},{dst.lon}/"


def tariff_text(tariff: Tariff) -> str:
    return (
        "💰 <b>Тарифи</b>\n\n"
        f"Подача машини: {fmt_price(tariff.base_price)}\n"
        f"Кілометр шляху: {fmt_price(tariff.price_per_km)}\n"
        f"Мінімальне замовлення: {fmt_price(tariff.min_price)}"
    )


def order_summary(src: Place, dst: Place, route: Route, price: int, tariff: Tariff) -> str:
    if route.estimated:
        distance = f"~{fmt_km(route.distance_km)} (приблизно)"
    elif route.duration_min:
        distance = f"{fmt_km(route.distance_km)} (≈ {fmt_duration(route.duration_min)} у дорозі)"
    else:
        distance = fmt_km(route.distance_km)

    return (
        "🚚 <b>Розрахунок перевезення</b>\n\n"
        f"📍 Звідки: {escape(src.address)}\n"
        f"🏁 Куди: {escape(dst.address)}\n"
        f"🛣 Відстань: {distance}\n"
        f"💰 Вартість: <b>{fmt_price(price)}</b>\n\n"
        f"<i>Подача {fmt_price(tariff.base_price)} + {fmt_price(tariff.price_per_km)}/км, "
        f"мінімум {fmt_price(tariff.min_price)}</i>\n"
        f'<a href="{map_url(src, dst)}">Маршрут на карті</a>'
    )
