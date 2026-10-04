"""Геокодинг (адрес → координаты) и расчёт расстояния по дорогам.

Сейчас используются бесплатные сервисы OpenStreetMap:
  * Nominatim — поиск адресов (лимит 1 запрос/сек, обязателен User-Agent).
    Поиск ограничен страной и прямоугольником области (по умолчанию — Харьковская),
    поэтому «Сумская 10» находится в Харькове, а не в другом городе;
  * OSRM — маршрут по дорогам.
Если OSRM недоступен, расстояние оценивается по прямой с коэффициентом.
"""

import asyncio
import logging
import math
from dataclasses import dataclass

import aiohttp

from bot.services.ru_uk import ukrainize

log = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class Place:
    address: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Route:
    distance_km: float
    duration_min: int | None
    # True — посчитано по прямой с коэффициентом, а не по дорогам
    estimated: bool


class GeoError(Exception):
    """Сервис карт не ответил или ответил ошибкой."""


def haversine_km(a: Place, b: Place) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _first(mapping: dict, keys: tuple[str, ...]) -> str | None:
    return next((mapping[k] for k in keys if mapping.get(k)), None)


def short_address(item: dict) -> str:
    """Собирает «Город, улица, дом» из ответа Nominatim вместо длинного display_name."""
    addr = item.get("address") or {}
    locality = _first(addr, ("city", "town", "village", "hamlet", "municipality"))
    street = _first(addr, ("road", "pedestrian", "footway", "square"))
    house = addr.get("house_number")
    name = item.get("name")

    if not street and not name:
        return ", ".join(item.get("display_name", "").split(", ")[:4])

    parts = [locality]
    if name and name not in (locality, street, house):
        parts.append(name)
    parts += [street, house]
    return ", ".join(p for p in parts if p)


class GeoService:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        nominatim_url: str,
        osrm_url: str,
        countries: str = "",
        viewbox: str = "",
        language: str = "uk",
        road_factor: float = 1.3,
        min_interval: float = 1.0,
    ) -> None:
        self._session = session
        self._nominatim_url = nominatim_url.rstrip("/")
        self._osrm_url = osrm_url.rstrip("/")
        self._countries = countries
        self._viewbox = viewbox
        self._language = language
        self._road_factor = road_factor
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def geocode(self, query: str) -> Place | None:
        """Ищет адрес. None — не найден, GeoError — сервис недоступен.

        Сначала ищем как написано (русские названия улиц находятся, если они есть в OSM),
        затем — переделанный на украинский лад запрос.
        """
        params = {"format": "jsonv2", "limit": 1, "addressdetails": 1, "accept-language": self._language}
        if self._countries:
            params["countrycodes"] = self._countries
        if self._viewbox:
            params["viewbox"] = self._viewbox
            params["bounded"] = 1

        for q in dict.fromkeys([query, ukrainize(query)]):
            items = await self._nominatim("search", {**params, "q": q})
            if items:
                item = items[0]
                return Place(short_address(item), float(item["lat"]), float(item["lon"]))
        return None

    async def reverse(self, lat: float, lon: float) -> Place:
        """Адрес по точке на карте. Координаты точные, так что при ошибке просто показываем их."""
        params = {"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "accept-language": self._language}
        try:
            item = await self._nominatim("reverse", params)
        except GeoError:
            log.warning("Reverse geocoding failed for %s,%s", lat, lon, exc_info=True)
            item = None
        if not item or "error" in item:
            return Place(f"{lat:.5f}, {lon:.5f}", lat, lon)
        return Place(short_address(item), lat, lon)

    async def route(self, a: Place, b: Place) -> Route:
        url = f"{self._osrm_url}/route/v1/driving/{a.lon},{a.lat};{b.lon},{b.lat}"
        try:
            data = await self._get_json(url, {"overview": "false"})
            if data.get("code") != "Ok" or not data.get("routes"):
                raise GeoError(f"OSRM: {data.get('code')}")
            best = data["routes"][0]
            return Route(
                distance_km=best["distance"] / 1000,
                duration_min=round(best["duration"] / 60),
                estimated=False,
            )
        except GeoError:
            log.warning("OSRM route failed, falling back to straight-line estimate", exc_info=True)
            return Route(haversine_km(a, b) * self._road_factor, None, estimated=True)

    async def _nominatim(self, endpoint: str, params: dict):
        # Политика Nominatim: не чаще 1 запроса в секунду
        async with self._lock:
            loop = asyncio.get_running_loop()
            wait = self._last_call + self._min_interval - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await self._get_json(f"{self._nominatim_url}/{endpoint}", params)
            finally:
                self._last_call = loop.time()

    async def _get_json(self, url: str, params: dict):
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise GeoError(f"{url}: HTTP {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            raise GeoError(f"{url}: {e!r}") from e
