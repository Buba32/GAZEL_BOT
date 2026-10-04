import aiosqlite

from bot.services.geo import Place

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      INTEGER PRIMARY KEY,
    phone      TEXT NOT NULL,
    first_name TEXT,
    username   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS addresses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(tg_id),
    address      TEXT NOT NULL,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    -- растёт при каждом использовании адреса: по нему сортируем «недавние»
    used_seq     INTEGER NOT NULL,
    UNIQUE (user_id, address)
);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(tg_id),
    from_address TEXT NOT NULL,
    from_lat     REAL NOT NULL,
    from_lon     REAL NOT NULL,
    to_address   TEXT NOT NULL,
    to_lat       REAL NOT NULL,
    to_lon       REAL NOT NULL,
    distance_km  REAL NOT NULL,
    price        INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

ORDER_NEW = "new"
ORDER_ACCEPTED = "accepted"
ORDER_REJECTED = "rejected"


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn, "Database.connect() не вызван"
        return self._conn

    # --- Пользователи ---

    async def get_user(self, tg_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cur:
            return await cur.fetchone()

    async def upsert_user(self, tg_id: int, phone: str, first_name: str | None, username: str | None) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (tg_id, phone, first_name, username) VALUES (?, ?, ?, ?)
            ON CONFLICT (tg_id) DO UPDATE SET
                phone = excluded.phone, first_name = excluded.first_name, username = excluded.username
            """,
            (tg_id, phone, first_name, username),
        )
        await self.conn.commit()

    # --- Адреса ---

    async def save_address(self, user_id: int, place: Place) -> None:
        await self.conn.execute(
            """
            INSERT INTO addresses (user_id, address, lat, lon, used_seq)
            VALUES (?, ?, ?, ?, (SELECT COALESCE(MAX(used_seq), 0) + 1 FROM addresses WHERE user_id = ?))
            ON CONFLICT (user_id, address) DO UPDATE SET
                lat = excluded.lat, lon = excluded.lon, used_seq = excluded.used_seq
            """,
            (user_id, place.address, place.lat, place.lon, user_id),
        )
        await self.conn.commit()

    async def recent_addresses(self, user_id: int, limit: int = 5) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM addresses WHERE user_id = ? ORDER BY used_seq DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            return list(await cur.fetchall())

    async def get_address(self, address_id: int, user_id: int) -> Place | None:
        async with self.conn.execute(
            "SELECT address, lat, lon FROM addresses WHERE id = ? AND user_id = ?", (address_id, user_id)
        ) as cur:
            row = await cur.fetchone()
        return Place(row["address"], row["lat"], row["lon"]) if row else None

    async def delete_address(self, address_id: int, user_id: int) -> None:
        await self.conn.execute("DELETE FROM addresses WHERE id = ? AND user_id = ?", (address_id, user_id))
        await self.conn.commit()

    # --- Заказы ---

    async def create_order(self, user_id: int, src: Place, dst: Place, distance_km: float, price: int) -> int:
        cur = await self.conn.execute(
            """
            INSERT INTO orders (user_id, from_address, from_lat, from_lon,
                                to_address, to_lat, to_lon, distance_km, price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, src.address, src.lat, src.lon, dst.address, dst.lat, dst.lon, distance_km, price),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get_order(self, order_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cur:
            return await cur.fetchone()

    async def user_orders(self, user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ) as cur:
            return list(await cur.fetchall())

    async def set_order_status(self, order_id: int, status: str) -> bool:
        """Меняет статус только у новой заявки. False — её уже обработали."""
        cur = await self.conn.execute(
            "UPDATE orders SET status = ? WHERE id = ? AND status = ?", (status, order_id, ORDER_NEW)
        )
        await self.conn.commit()
        return cur.rowcount > 0
