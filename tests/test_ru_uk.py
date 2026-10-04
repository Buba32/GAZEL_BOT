import pytest

from bot.services.ru_uk import ukrainize


@pytest.mark.parametrize(
    ("ru", "uk"),
    [
        ("Пушкинская 10", "Пушкінська 10"),
        ("Харьков, ул. Клочковская, 5", "Харків, вул. Клочківська, 5"),
        ("Чугуев, Харьковская 5", "Чугуїв, Харківська 5"),
        ("проспект Героев Труда 7", "проспект Героїв Праці 7"),
        ("Полтавский шлях 30", "Полтавський шлях 30"),
        ("пер. Короленко 2", "пров. Короленко 2"),
        ("Купянск, Соборная 1", "Куп'янськ, Соборна 1"),
    ],
)
def test_ukrainize(ru, uk):
    assert ukrainize(ru) == uk


def test_house_number_letters_untouched():
    assert ukrainize("Сумская 10д") == "Сумська 10д"


def test_ukrainian_text_unchanged():
    assert ukrainize("Харків, Сумська вулиця, 10") == "Харків, Сумська вулиця, 10"
