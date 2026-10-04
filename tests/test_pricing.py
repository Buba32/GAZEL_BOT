from bot.services.pricing import Tariff, calc_price

TARIFF = Tariff(base_price=1000, price_per_km=45, min_price=2000)


def test_short_trip_costs_min_price():
    assert calc_price(1, TARIFF) == 2000


def test_base_plus_per_km():
    assert calc_price(30, TARIFF) == 1000 + 30 * 45


def test_rounds_up_to_ten_rubles():
    # 1000 + 30.33 * 45 = 2364.85
    assert calc_price(30.33, TARIFF) == 2370


def test_float_noise_does_not_bump_price():
    # 100 * 1.1 = 110.00000000000001 во float
    assert calc_price(100, Tariff(base_price=0, price_per_km=1.1, min_price=0)) == 110
