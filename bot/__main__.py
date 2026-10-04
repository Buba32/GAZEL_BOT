import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import load_config
from bot.db import Database
from bot.handlers import setup_routers
from bot.services.geo import GeoService


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()

    db = Database(config.db_path)
    await db.connect()
    http = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=15),
        headers={"User-Agent": config.user_agent},
    )
    geo = GeoService(
        http,
        nominatim_url=config.nominatim_url,
        osrm_url=config.osrm_url,
        countries=config.geocoder_countries,
        viewbox=config.geocoder_viewbox,
        language=config.geocoder_language,
        road_factor=config.road_factor,
    )

    bot = Bot(
        config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(setup_routers())

    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="cancel", description="Отменить заказ"),
            ]
        )
        await dp.start_polling(bot, db=db, geo=geo, config=config)
    finally:
        await http.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
