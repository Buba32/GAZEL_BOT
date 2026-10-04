import pytest

from bot.services.geo import GeoError, Place, haversine_km, short_address
from tests.conftest import StubGeo

KHARKIV = Place("Харків", 49.9935, 36.2304)
KYIV = Place("Київ", 50.4501, 30.5234)


def test_haversine_kharkiv_kyiv():
    assert haversine_km(KHARKIV, KYIV) == pytest.approx(410, abs=5)


def test_short_address_house():
    item = {
        "name": "",
        "display_name": "10, Сумська вулиця, Шевченківський район, Харків, Україна",
        "address": {"house_number": "10", "road": "Сумська вулиця", "city": "Харків"},
    }
    assert short_address(item) == "Харків, Сумська вулиця, 10"


def test_short_address_named_place():
    item = {
        "name": "Міжнародний аеропорт «Харків»",
        "display_name": "Міжнародний аеропорт «Харків», Харків, Харківська область, Україна",
        "address": {"aeroway": "Міжнародний аеропорт «Харків»", "city": "Харків"},
    }
    assert short_address(item) == "Харків, Міжнародний аеропорт «Харків»"


def test_short_address_falls_back_to_display_name():
    item = {"name": "", "display_name": "a, b, c, d, e, f", "address": {"state": "x"}}
    assert short_address(item) == "a, b, c, d"


async def test_geocode_found():
    geo = StubGeo(
        {
            "http://nominatim/search": [
                {"lat": "50.0", "lon": "36.2", "name": "", "address": {"road": "Сумська вулиця", "city": "Харків"}}
            ]
        }
    )
    place = await geo.geocode("Сумская")
    assert place == Place("Харків, Сумська вулиця", 50.0, 36.2)
    _, params = geo.calls[0]
    # Поиск только по Украине и внутри Харьковской области
    assert params["countrycodes"] == "ua"
    assert params["viewbox"] == "34.8,50.5,38.2,48.5"
    assert params["bounded"] == 1


async def test_geocode_not_found():
    geo = StubGeo({"http://nominatim/search": []})
    assert await geo.geocode("абырвалг") is None


async def test_geocode_service_down_raises():
    geo = StubGeo({"http://nominatim/search": GeoError("HTTP 503")})
    with pytest.raises(GeoError):
        await geo.geocode("Сумская")


async def test_reverse_falls_back_to_coordinates():
    geo = StubGeo({"http://nominatim/reverse": GeoError("timeout")})
    place = await geo.reverse(50.123456, 36.654321)
    assert place == Place("50.12346, 36.65432", 50.123456, 36.654321)


async def test_route_by_roads():
    geo = StubGeo({"http://osrm/route": {"code": "Ok", "routes": [{"distance": 480_300, "duration": 21_600}]}})
    route = await geo.route(KHARKIV, KYIV)
    assert route.distance_km == pytest.approx(480.3)
    assert route.duration_min == 360
    assert not route.estimated
    url, _ = geo.calls[0]
    assert url == "http://osrm/route/v1/driving/36.2304,49.9935;30.5234,50.4501"


async def test_route_falls_back_to_estimate():
    geo = StubGeo({"http://osrm/route": GeoError("HTTP 502")}, road_factor=1.5)
    route = await geo.route(KHARKIV, KYIV)
    assert route.estimated
    assert route.duration_min is None
    assert route.distance_km == pytest.approx(haversine_km(KHARKIV, KYIV) * 1.5)


async def test_russian_street_falls_back_to_ukrainian_query():
    # Улицы нет в OSM под русским названием, но есть под украинским
    def search(url, params):
        if params["q"] == "Пушкінська 5":
            return [
                {"lat": "50.0", "lon": "36.24", "name": "", "address": {"road": "Пушкінська вулиця", "city": "Харків"}}
            ]
        return []

    geo = StubGeo({"http://nominatim/search": search})
    place = await geo.geocode("Пушкинская 5")
    assert place == Place("Харків, Пушкінська вулиця", 50.0, 36.24)
    assert [params["q"] for _, params in geo.calls] == ["Пушкинская 5", "Пушкінська 5"]


async def test_ukrainian_query_is_sent_once():
    geo = StubGeo({"http://nominatim/search": []})
    assert await geo.geocode("Сумська 10") is None
    assert len(geo.calls) == 1
