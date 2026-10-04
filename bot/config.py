import os
from dataclasses import dataclass

from dotenv import load_dotenv

from bot.services.pricing import Tariff

# Харьковская область с небольшим запасом по краям: lon_min, lat_max, lon_max, lat_min
KHARKIV_OBLAST_VIEWBOX = "34.8,50.5,38.2,48.5"


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    # Куда падают новые заявки. Если не задан — каждому админу в личку.
    admin_chat_id: int | None
    # Канал с новостями: @username или -100…
    channel_id: str | None
    channel_url: str | None
    db_path: str
    tariff: Tariff
    geocoder_countries: str
    # Область поиска адресов «lon1,lat1,lon2,lat2»; пусто — без ограничений
    geocoder_viewbox: str
    geocoder_language: str
    nominatim_url: str
    osrm_url: str
    user_agent: str
    road_factor: float


def _ids(value: str) -> frozenset[int]:
    return frozenset(int(x) for x in value.replace(" ", "").split(",") if x)


def _optional_int(value: str | None) -> int | None:
    return int(value) if value else None


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан: скопируйте .env.example в .env и заполните")

    return Config(
        bot_token=token,
        admin_ids=_ids(os.getenv("ADMIN_IDS", "")),
        admin_chat_id=_optional_int(os.getenv("ADMIN_CHAT_ID")),
        channel_id=os.getenv("CHANNEL_ID") or None,
        channel_url=os.getenv("CHANNEL_URL") or None,
        db_path=os.getenv("DB_PATH", "gazel.db"),
        tariff=Tariff(
            base_price=int(os.getenv("BASE_PRICE", "600")),
            price_per_km=float(os.getenv("PRICE_PER_KM", "25")),
            min_price=int(os.getenv("MIN_PRICE", "1000")),
        ),
        geocoder_countries=os.getenv("GEOCODER_COUNTRIES", "ua"),
        geocoder_viewbox=os.getenv("GEOCODER_VIEWBOX", KHARKIV_OBLAST_VIEWBOX),
        geocoder_language=os.getenv("GEOCODER_LANGUAGE", "uk"),
        nominatim_url=os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org"),
        osrm_url=os.getenv("OSRM_URL", "https://router.project-osrm.org"),
        user_agent=os.getenv("USER_AGENT", "GazelBot/0.1"),
        road_factor=float(os.getenv("ROAD_FACTOR", "1.3")),
    )
