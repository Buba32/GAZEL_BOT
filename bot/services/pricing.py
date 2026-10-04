import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Tariff:
    base_price: int  # подача машины, ₽
    price_per_km: float  # ₽ за километр пути
    min_price: int  # минимальный заказ, ₽
    round_to: int = 10  # округляем вверх до N ₽


def calc_price(distance_km: float, tariff: Tariff) -> int:
    raw = tariff.base_price + distance_km * tariff.price_per_km
    raw = max(raw, tariff.min_price)
    # round(…, 2) убирает хвосты float, чтобы 1450.0000001 не стало 1460
    return math.ceil(round(raw, 2) / tariff.round_to) * tariff.round_to
