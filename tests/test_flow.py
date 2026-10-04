"""Сквозной сценарий через настоящий Dispatcher, но без сети: запросы к Telegram перехватываются."""

from datetime import datetime
from itertools import count

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    CopyMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
)
from aiogram.types import Chat, Message, MessageId, Update

from bot.handlers import setup_routers
from bot.keyboards import BTN_CONTACT, MENU_ORDER, MENU_ORDERS, AdminOrderCb, OrderCb
from tests.conftest import StubGeo

CLIENT = 500
ADMIN = 1

# Роутеры — синглтоны модулей и подключаются к диспетчеру один раз,
# поэтому диспетчер общий, а хранилище FSM пересоздаётся на каждый тест.
DP = Dispatcher()
DP.include_router(setup_routers())


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list = []
        self._ids = count(1000)

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self._ids),
                date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private")
                if isinstance(method.chat_id, int)
                else Chat(id=-100, type="channel", username=method.chat_id.lstrip("@")),
                text=method.text,
            )
        if isinstance(method, CopyMessage):
            return MessageId(message_id=next(self._ids))
        return True

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError

    async def close(self) -> None:
        pass

    def sent(self, chat_id: int | str | None = None) -> list[SendMessage]:
        return [r for r in self.requests if isinstance(r, SendMessage) and chat_id in (None, r.chat_id)]


def geo_responses():
    places = {
        "сумская 10": {
            "lat": "50.0005",
            "lon": "36.2325",
            "address": {"road": "Сумська вулиця", "house_number": "10", "city": "Харків"},
        },
        "чугуев, харьковская 5": {
            "lat": "49.8350",
            "lon": "36.6880",
            "address": {"road": "Харківська вулиця", "house_number": "5", "city": "Чугуїв"},
        },
    }

    def search(url, params):
        item = places.get(params["q"].lower())
        return [{"name": "", **item}] if item else []

    return {
        "http://nominatim/search": search,
        "http://osrm/route": {"code": "Ok", "routes": [{"distance": 24_500, "duration": 2_100}]},
    }


class Harness:
    def __init__(self, db, config) -> None:
        self.session = FakeSession()
        self.bot = Bot(config.bot_token, session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        self.dp = DP
        self.dp.fsm.storage = MemoryStorage()
        self.db, self.config = db, config
        self.geo = StubGeo(geo_responses())
        self._ids = count(1)

    def _user(self, uid: int) -> dict:
        return {"id": uid, "is_bot": False, "first_name": "Иван", "username": "ivan"}

    async def _feed(self, data: dict) -> None:
        update = Update.model_validate({"update_id": next(self._ids), **data}, context={"bot": self.bot})
        await self.dp.feed_update(self.bot, update, db=self.db, geo=self.geo, config=self.config)

    async def message(self, uid: int, **content) -> None:
        msg = {
            "message_id": next(self._ids),
            "date": 0,
            "chat": {"id": uid, "type": "private"},
            "from": self._user(uid),
        }
        await self._feed({"message": {**msg, **content}})

    async def press(self, uid: int, data: str, text: str = "…") -> None:
        msg = {"message_id": next(self._ids), "date": 0, "chat": {"id": uid, "type": "private"}, "text": text}
        await self._feed(
            {
                "callback_query": {
                    "id": str(next(self._ids)),
                    "from": self._user(uid),
                    "chat_instance": "x",
                    "data": data,
                    "message": msg,
                }
            }
        )


@pytest.fixture
async def h(db, config):
    harness = Harness(db, config)
    yield harness
    await harness.bot.session.close()


async def register(h: Harness, uid: int = CLIENT) -> None:
    await h.message(uid, text="/start")
    await h.message(uid, contact={"phone_number": "380501234567", "first_name": "Иван", "user_id": uid})


async def test_unregistered_user_is_asked_for_phone(h):
    await h.message(CLIENT, text=MENU_ORDER)
    reply = h.session.sent(CLIENT)[-1]
    assert "поділіться номером" in reply.text
    assert reply.reply_markup.keyboard[0][0].text == BTN_CONTACT


async def test_foreign_contact_is_rejected(h):
    await h.message(CLIENT, contact={"phone_number": "+380000000000", "first_name": "Чужой", "user_id": 777})
    assert await h.db.get_user(CLIENT) is None
    assert "<b>свій</b>" in h.session.sent(CLIENT)[-1].text


async def test_full_order_flow(h):
    await register(h)
    assert (await h.db.get_user(CLIENT))["phone"] == "+380501234567"

    await h.message(CLIENT, text=MENU_ORDER)
    assert "Звідки" in h.session.sent(CLIENT)[-1].text

    await h.message(CLIENT, text="абырвалг")
    assert "Не вдалося знайти" in h.session.sent(CLIENT)[-1].text

    await h.message(CLIENT, text="Сумская 10")
    texts = [m.text for m in h.session.sent(CLIENT)[-2:]]
    assert "Харків, Сумська вулиця, 10" in texts[0]
    assert "Куди" in texts[1]

    await h.message(CLIENT, text="Чугуев, Харьковская 5")
    summary = h.session.sent(CLIENT)[-1].text
    assert "24,5 км" in summary
    assert "≈ 35 хв у дорозі" in summary
    # 600 + 24.5 * 25 = 1212.5 → округление вверх до 10 грн
    assert "1 220 грн" in summary
    assert "https://www.google.com/maps/dir/50.0005,36.2325/49.835,36.688/" in summary

    await h.press(CLIENT, OrderCb(action="confirm").pack())
    edit = next(r for r in reversed(h.session.requests) if isinstance(r, EditMessageText))
    assert "Заявку №1 оформлено" in edit.text

    order = await h.db.get_order(1)
    assert (order["from_address"], order["to_address"], order["price"]) == (
        "Харків, Сумська вулиця, 10",
        "Чугуїв, Харківська вулиця, 5",
        1220,
    )
    assert len(await h.db.recent_addresses(CLIENT)) == 2

    admin_msg = h.session.sent(ADMIN)[-1]
    assert "Заявка №1" in admin_msg.text
    assert "+380501234567" in admin_msg.text

    # Повторное нажатие «Оформить» не создаёт второй заказ
    await h.press(CLIENT, OrderCb(action="confirm").pack())
    assert len(await h.db.user_orders(CLIENT)) == 1

    await h.press(ADMIN, AdminOrderCb(action="accept", order_id=1).pack(), text=admin_msg.text)
    assert (await h.db.get_order(1))["status"] == "accepted"
    assert "прийнято" in h.session.sent(CLIENT)[-1].text

    await h.message(CLIENT, text=MENU_ORDERS)
    assert "✅ Прийнята" in h.session.sent(CLIENT)[-1].text


async def test_same_address_twice_is_rejected(h):
    await register(h)
    await h.message(CLIENT, text=MENU_ORDER)
    await h.message(CLIENT, text="Сумская 10")
    await h.message(CLIENT, text="Сумская 10")
    assert "збігається" in h.session.sent(CLIENT)[-1].text


async def test_location_input(h):
    await register(h)
    h.geo.responses["http://nominatim/reverse"] = {
        "name": "",
        "address": {"road": "Сумська вулиця", "house_number": "10", "city": "Харків"},
    }
    await h.message(CLIENT, text=MENU_ORDER)
    await h.message(CLIENT, location={"latitude": 50.0005, "longitude": 36.2325})
    assert "Харків, Сумська вулиця, 10" in h.session.sent(CLIENT)[-2].text


async def test_non_admin_cannot_accept(h):
    await register(h)
    await h.db.create_order(
        CLIENT, *[(await h.geo.geocode(q)) for q in ("Сумская 10", "Чугуев, Харьковская 5")], 24.5, 1220
    )
    await h.press(CLIENT, AdminOrderCb(action="accept", order_id=1).pack())
    assert (await h.db.get_order(1))["status"] == "new"
    answer = next(r for r in reversed(h.session.requests) if isinstance(r, AnswerCallbackQuery))
    assert answer.text == "Лише для адміністраторів"


async def test_admin_post_to_channel(h):
    await h.message(ADMIN, text="/post Скидка 10% на переезды!")
    post = h.session.sent("@gazel_news")[-1]
    assert post.text == "Скидка 10% на переезды!"
    assert "Опубліковано" in h.session.sent(ADMIN)[-1].text


async def test_non_admin_post_is_ignored(h):
    await register(h)
    await h.message(CLIENT, text="/post спам")
    assert h.session.sent("@gazel_news") == []


async def test_cancel_returns_to_menu(h):
    await register(h)
    await h.message(CLIENT, text=MENU_ORDER)
    await h.message(CLIENT, text="Сумская 10")
    await h.message(CLIENT, text="Чугуев, Харьковская 5")
    await h.press(CLIENT, OrderCb(action="cancel").pack())
    assert any(isinstance(r, EditMessageReplyMarkup) for r in h.session.requests)
    assert await h.db.user_orders(CLIENT) == []
