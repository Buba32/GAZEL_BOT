from aiogram import Router

from bot.handlers import admin, fallback, menu, order, start


def setup_routers() -> Router:
    root = Router(name="root")
    # Порядок важен: fallback ловит всё, поэтому последний
    root.include_routers(start.router, admin.router, menu.router, order.router, fallback.router)
    return root
