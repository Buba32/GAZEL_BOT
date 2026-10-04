import pytest

from bot.services.geo import GeoError, Place, haversine_km, short_address
from tests.conftest import StubGeo

MOSCOW = Place("Москва", 55.7558, 37.6173)
SPB = Place("Санкт-Петербург", 59.9386, 30.3141)


def test_haversine_moscow_spb():
    assert haversine_km(MOSCOW, SPB) == pytest.approx(634, abs=3)


def test_short_address_house():
    item = {
        "name": "",
        "display_name": "12, Тверская улица, Тверской район, Москва, Россия",
        "address": {"house_number": "12", "road": "Тверская улица", "city": "Москва"},
    }
    assert short_address(item) == "Москва, Тверская улица, 12"


def test_short_address_named_place():
    item = {
        "name": "Шереметьево",
        "display_name": "Шереметьево, Химки, Московская область, Россия",
        "address": {"aeroway": "Шереметьево", "city": "Химки"},
    }
    assert short_address(item) == "Химки, Шереметьево"


def test_short_address_falls_back_to_display_name():
    item = {"name": "", "display_name": "a, b, c, d, e, f", "address": {"state": "x"}}
    assert short_address(item) == "a, b, c, d"


async def test_geocode_found():
    geo = StubGeo(
        {
            "http://nominatim/search": [
                {"lat": "55.7", "lon": "37.6", "name": "", "address": {"road": "Тверская улица", "city": "Москва"}}
            ]
        }
    )
    place = await geo.geocode("Тверская")
    assert place == Place("Москва, Тверская улица", 55.7, 37.6)
    _, params = geo.calls[0]
    assert params["countrycodes"] == "ru"


async def test_geocode_not_found():
    geo = StubGeo({"http://nominatim/search": []})
    assert await geo.geocode("абырвалг") is None


async def test_geocode_service_down_raises():
    geo = StubGeo({"http://nominatim/search": GeoError("HTTP 503")})
    with pytest.raises(GeoError):
        await geo.geocode("Тверская")


async def test_reverse_falls_back_to_coordinates():
    geo = StubGeo({"http://nominatim/reverse": GeoError("timeout")})
    place = await geo.reverse(55.123456, 37.654321)
    assert place == Place("55.12346, 37.65432", 55.123456, 37.654321)


async def test_route_by_roads():
    geo = StubGeo({"http://osrm/route": {"code": "Ok", "routes": [{"distance": 712_300, "duration": 30_600}]}})
    route = await geo.route(MOSCOW, SPB)
    assert route.distance_km == pytest.approx(712.3)
    assert route.duration_min == 510
    assert not route.estimated
    url, _ = geo.calls[0]
    assert url == "http://osrm/route/v1/driving/37.6173,55.7558;30.3141,59.9386"


async def test_route_falls_back_to_estimate():
    geo = StubGeo({"http://osrm/route": GeoError("HTTP 502")}, road_factor=1.5)
    route = await geo.route(MOSCOW, SPB)
    assert route.estimated
    assert route.duration_min is None
    assert route.distance_km == pytest.approx(haversine_km(MOSCOW, SPB) * 1.5)
