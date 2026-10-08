"""Base de datos SQLite (async). Un solo archivo: data/bot.db

`settings` es un almacén clave-valor por servidor (JSON). Los cogs nuevos pueden guardar
su configuración ahí sin migraciones: db.set_setting(guild_id, "clave", valor).
Las tablas específicas (casos, acciones temporales...) están abajo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    value    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS cases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    case_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    mod_id     INTEGER NOT NULL,
    action     TEXT    NOT NULL,
    reason     TEXT,
    created_at REAL    NOT NULL,
    expires_at REAL,
    active     INTEGER NOT NULL DEFAULT 1,
    UNIQUE (guild_id, case_id)
);
CREATE INDEX IF NOT EXISTS idx_cases_user ON cases (guild_id, user_id);

CREATE TABLE IF NOT EXISTS timed_actions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    action     TEXT    NOT NULL,
    expires_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_timed_expires ON timed_actions (expires_at);

CREATE TABLE IF NOT EXISTS afk (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    reason   TEXT    NOT NULL,
    since    REAL    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    guild_id   INTEGER,
    channel_id INTEGER,
    message    TEXT    NOT NULL,
    remind_at  REAL    NOT NULL,
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (remind_at);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders (user_id);

CREATE TABLE IF NOT EXISTS todos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    content    TEXT    NOT NULL,
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_todos_user ON todos (user_id);

CREATE TABLE IF NOT EXISTS jail_roles (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    role_ids TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ---- SQL genérico -------------------------------------------------
    async def execute(self, sql: str, *params: Any) -> int:
        """Ejecuta y hace commit. Devuelve lastrowid."""
        async with self._conn.execute(sql, params) as cursor:
            await self._conn.commit()
            return cursor.lastrowid

    async def fetchone(self, sql: str, *params: Any):
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql: str, *params: Any) -> List[aiosqlite.Row]:
        async with self._conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    # ---- Ajustes por servidor (clave-valor JSON) ----------------------
    async def get_setting(self, guild_id: int, key: str, default: Any = None) -> Any:
        row = await self.fetchone(
            "SELECT value FROM settings WHERE guild_id = ? AND key = ?", guild_id, key
        )
        return json.loads(row["value"]) if row else default

    async def set_setting(self, guild_id: int, key: str, value: Any) -> None:
        await self.execute(
            "INSERT INTO settings (guild_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, key) DO UPDATE SET value = excluded.value",
            guild_id,
            key,
            json.dumps(value),
        )

    async def del_setting(self, guild_id: int, key: str) -> None:
        await self.execute("DELETE FROM settings WHERE guild_id = ? AND key = ?", guild_id, key)
