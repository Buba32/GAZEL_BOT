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
        "москва, тверская 12": {
            "lat": "55.7650",
            "lon": "37.6050",
            "address": {"road": "Тверская улица", "house_number": "12", "city": "Москва"},
        },
        "химки, ленинградское шоссе 1": {
            "lat": "55.8890",
            "lon": "37.4440",
            "address": {"road": "Ленинградское шоссе", "house_number": "1", "city": "Химки"},
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
    await h.message(uid, contact={"phone_number": "79991234567", "first_name": "Иван", "user_id": uid})


async def test_unregistered_user_is_asked_for_phone(h):
    await h.message(CLIENT, text=MENU_ORDER)
    reply = h.session.sent(CLIENT)[-1]
    assert "поделитесь номером" in reply.text
    assert reply.reply_markup.keyboard[0][0].text == BTN_CONTACT


async def test_foreign_contact_is_rejected(h):
    await h.message(CLIENT, contact={"phone_number": "+70000000000", "first_name": "Чужой", "user_id": 777})
    assert await h.db.get_user(CLIENT) is None
    assert "<b>свой</b>" in h.session.sent(CLIENT)[-1].text


async def test_full_order_flow(h):
    await register(h)
    assert (await h.db.get_user(CLIENT))["phone"] == "+79991234567"

    await h.message(CLIENT, text=MENU_ORDER)
    assert "Откуда" in h.session.sent(CLIENT)[-1].text

    await h.message(CLIENT, text="абырвалг")
    assert "Не нашёл" in h.session.sent(CLIENT)[-1].text

    await h.message(CLIENT, text="Москва, Тверская 12")
    texts = [m.text for m in h.session.sent(CLIENT)[-2:]]
    assert "Москва, Тверская улица, 12" in texts[0]
    assert "Куда" in texts[1]

    await h.message(CLIENT, text="Химки, Ленинградское шоссе 1")
    summary = h.session.sent(CLIENT)[-1].text
    assert "24,5 км" in summary
    assert "≈ 35 мин" in summary
    # 1000 + 24.5 * 45 = 2102.5 → округление вверх до 10 ₽
    assert "2 110 ₽" in summary

    await h.press(CLIENT, OrderCb(action="confirm").pack())
    edit = next(r for r in reversed(h.session.requests) if isinstance(r, EditMessageText))
    assert "Заявка №1 оформлена" in edit.text

    order = await h.db.get_order(1)
    assert (order["from_address"], order["to_address"], order["price"]) == (
        "Москва, Тверская улица, 12",
        "Химки, Ленинградское шоссе, 1",
        2110,
    )
    assert len(await h.db.recent_addresses(CLIENT)) == 2

    admin_msg = h.session.sent(ADMIN)[-1]
    assert "Заявка №1" in admin_msg.text
    assert "+79991234567" in admin_msg.text

    # Повторное нажатие «Оформить» не создаёт второй заказ
    await h.press(CLIENT, OrderCb(action="confirm").pack())
    assert len(await h.db.user_orders(CLIENT)) == 1

    await h.press(ADMIN, AdminOrderCb(action="accept", order_id=1).pack(), text=admin_msg.text)
    assert (await h.db.get_order(1))["status"] == "accepted"
    assert "принята" in h.session.sent(CLIENT)[-1].text

    await h.message(CLIENT, text=MENU_ORDERS)
    assert "✅ Принята" in h.session.sent(CLIENT)[-1].text


async def test_same_address_twice_is_rejected(h):
    await register(h)
    await h.message(CLIENT, text=MENU_ORDER)
    await h.message(CLIENT, text="Москва, Тверская 12")
    await h.message(CLIENT, text="Москва, Тверская 12")
    assert "совпадает" in h.session.sent(CLIENT)[-1].text


async def test_location_input(h):
    await register(h)
    h.geo.responses["http://nominatim/reverse"] = {
        "name": "",
        "address": {"road": "Тверская улица", "house_number": "12", "city": "Москва"},
    }
    await h.message(CLIENT, text=MENU_ORDER)
    await h.message(CLIENT, location={"latitude": 55.765, "longitude": 37.605})
    assert "Москва, Тверская улица, 12" in h.session.sent(CLIENT)[-2].text


async def test_non_admin_cannot_accept(h):
    await register(h)
    await h.db.create_order(
        CLIENT, *[(await h.geo.geocode(q)) for q in ("Москва, Тверская 12", "Химки, Ленинградское шоссе 1")], 24.5, 2110
    )
    await h.press(CLIENT, AdminOrderCb(action="accept", order_id=1).pack())
    assert (await h.db.get_order(1))["status"] == "new"
    answer = next(r for r in reversed(h.session.requests) if isinstance(r, AnswerCallbackQuery))
    assert answer.text == "Только для администраторов"


async def test_admin_post_to_channel(h):
    await h.message(ADMIN, text="/post Скидка 10% на переезды!")
    post = h.session.sent("@gazel_news")[-1]
    assert post.text == "Скидка 10% на переезды!"
    assert "Опубликовано" in h.session.sent(ADMIN)[-1].text


async def test_non_admin_post_is_ignored(h):
    await register(h)
    await h.message(CLIENT, text="/post спам")
    assert h.session.sent("@gazel_news") == []


async def test_cancel_returns_to_menu(h):
    await register(h)
    await h.message(CLIENT, text=MENU_ORDER)
    await h.message(CLIENT, text="Москва, Тверская 12")
    await h.message(CLIENT, text="Химки, Ленинградское шоссе 1")
    await h.press(CLIENT, OrderCb(action="cancel").pack())
    assert any(isinstance(r, EditMessageReplyMarkup) for r in h.session.requests)
    assert await h.db.user_orders(CLIENT) == []
