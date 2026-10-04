from bot.db import ORDER_ACCEPTED, ORDER_REJECTED
from bot.services.geo import Place

A = Place("Харків, Сумська вулиця, 10", 50.0005, 36.2325)
B = Place("Чугуїв, Харківська вулиця, 5", 49.8350, 36.6880)


async def test_user_upsert(db):
    assert await db.get_user(10) is None
    await db.upsert_user(10, "+380500000000", "Иван", None)
    await db.upsert_user(10, "+380501111111", "Иван", "ivan")
    user = await db.get_user(10)
    assert user["phone"] == "+380501111111"
    assert user["username"] == "ivan"


async def test_addresses_dedup_and_recent_first(db):
    await db.upsert_user(10, "+7", None, None)
    await db.save_address(10, A)
    await db.save_address(10, B)
    await db.save_address(10, A)  # повтор — не дублируется

    rows = await db.recent_addresses(10)
    assert [r["address"] for r in rows] == [A.address, B.address]


async def test_address_belongs_to_owner(db):
    await db.upsert_user(10, "+7", None, None)
    await db.upsert_user(20, "+7", None, None)
    await db.save_address(10, A)
    address_id = (await db.recent_addresses(10))[0]["id"]

    assert await db.get_address(address_id, 20) is None
    await db.delete_address(address_id, 20)
    assert await db.get_address(address_id, 10) == A

    await db.delete_address(address_id, 10)
    assert await db.recent_addresses(10) == []


async def test_order_status_changes_once(db):
    await db.upsert_user(10, "+7", None, None)
    order_id = await db.create_order(10, A, B, 21.5, 2000)

    order = await db.get_order(order_id)
    assert order["status"] == "new"
    assert order["to_address"] == B.address

    assert await db.set_order_status(order_id, ORDER_ACCEPTED)
    assert not await db.set_order_status(order_id, ORDER_REJECTED)
    assert (await db.get_order(order_id))["status"] == ORDER_ACCEPTED
    assert [o["id"] for o in await db.user_orders(10)] == [order_id]
