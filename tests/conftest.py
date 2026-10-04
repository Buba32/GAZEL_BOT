import pytest

from bot.config import Config
from bot.db import Database
from bot.services.geo import GeoService
from bot.services.pricing import Tariff


class StubGeo(GeoService):
    """GeoService без сети: ответы Nominatim/OSRM подставляются из словаря по URL-эндпоинту."""

    def __init__(self, responses: dict | None = None, road_factor: float = 1.3) -> None:
        super().__init__(
            session=None,
            nominatim_url="http://nominatim",
            osrm_url="http://osrm",
            countries="ua",
            viewbox="34.8,50.5,38.2,48.5",
            road_factor=road_factor,
            min_interval=0,
        )
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def _get_json(self, url: str, params: dict):
        self.calls.append((url, params))
        for prefix, response in self.responses.items():
            if url.startswith(prefix):
                result = response(url, params) if callable(response) else response
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"Unexpected request: {url}")


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def config() -> Config:
    return Config(
        bot_token="42:TEST",
        admin_ids=frozenset({1}),
        admin_chat_id=None,
        channel_id="@gazel_news",
        channel_url="https://t.me/gazel_news",
        db_path=":memory:",
        tariff=Tariff(base_price=600, price_per_km=25, min_price=1000),
        geocoder_countries="ua",
        geocoder_viewbox="34.8,50.5,38.2,48.5",
        geocoder_language="uk",
        nominatim_url="http://nominatim",
        osrm_url="http://osrm",
        user_agent="test",
        road_factor=1.3,
    )
