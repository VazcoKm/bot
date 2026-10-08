"""Casos de moderación: registro en la base de datos, modlog y aviso por DM."""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, List, Optional

import discord

from config import Colors
from core.emojis import emojis
from core.utils import format_timedelta, truncate

# acción: (nombre visible, participio para el DM, color)
ACTIONS = {
    "ban": ("Ban", "baneado", Colors.ERROR),
    "unban": ("Unban", "desbaneado", Colors.SUCCESS),
    "kick": ("Kick", "expulsado", Colors.ERROR),
    "softban": ("Softban", "expulsado (softban)", Colors.ERROR),
    "tempban": ("Tempban", "baneado temporalmente", Colors.ERROR),
    "mute": ("Mute", "silenciado", Colors.WARN),
    "unmute": ("Unmute", "des-silenciado", Colors.SUCCESS),
    "warn": ("Warn", "advertido", Colors.WARN),
    "jail": ("Jail", "encarcelado", Colors.ERROR),
    "unjail": ("Unjail", "liberado de la cárcel", Colors.SUCCESS),
}


def audit_reason(moderator: Any, reason: Optional[str]) -> str:
    """Texto para el registro de auditoría de Discord (máx. 512 caracteres)."""
    return truncate(f"{moderator} ({moderator.id}): {reason or 'Sin razón especificada'}", 512)


async def log(
    bot,
    guild: discord.Guild,
    user: Any,
    moderator: Any,
    action: str,
    reason: Optional[str] = None,
    *,
    expires_at: Optional[float] = None,
    notify: bool = True,
) -> int:
    """Guarda un caso, lo manda al canal de modlog y devuelve su número."""
    row_id = await bot.db.execute(
        "INSERT INTO cases (guild_id, case_id, user_id, mod_id, action, reason, created_at, expires_at) "
        "VALUES (?, (SELECT COALESCE(MAX(case_id), 0) + 1 FROM cases WHERE guild_id = ?), ?, ?, ?, ?, ?, ?)",
        guild.id,
        guild.id,
        user.id,
        moderator.id,
        action,
        reason,
        time.time(),
        expires_at,
    )
    row = await bot.db.fetchone("SELECT case_id FROM cases WHERE id = ?", row_id)
    case_id = row["case_id"]
    if notify:
        await send_modlog(bot, guild, case_id)
    return case_id


async def get(bot, guild_id: int, case_id: int):
    return await bot.db.fetchone(
        "SELECT * FROM cases WHERE guild_id = ? AND case_id = ?", guild_id, case_id
    )


async def user_cases(
    bot,
    guild_id: int,
    user_id: int,
    *,
    action: Optional[str] = None,
    active_only: bool = False,
    limit: int = 200,
) -> List[Any]:
    sql = "SELECT * FROM cases WHERE guild_id = ? AND user_id = ?"
    params: List[Any] = [guild_id, user_id]
    if action:
        sql += " AND action = ?"
        params.append(action)
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY case_id DESC LIMIT ?"
    params.append(limit)
    return await bot.db.fetchall(sql, *params)


async def recent(bot, guild_id: int, limit: int = 100) -> List[Any]:
    return await bot.db.fetchall(
        "SELECT * FROM cases WHERE guild_id = ? ORDER BY case_id DESC LIMIT ?", guild_id, limit
    )


async def count_active(bot, guild_id: int, user_id: int, action: str) -> int:
    row = await bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM cases WHERE guild_id = ? AND user_id = ? AND action = ? AND active = 1",
        guild_id,
        user_id,
        action,
    )
    return row["n"]


async def deactivate(bot, guild_id: int, case_id: int) -> None:
    await bot.db.execute(
        "UPDATE cases SET active = 0 WHERE guild_id = ? AND case_id = ?", guild_id, case_id
    )


async def clear_active(bot, guild_id: int, user_id: int, action: str) -> int:
    n = await count_active(bot, guild_id, user_id, action)
    if n:
        await bot.db.execute(
            "UPDATE cases SET active = 0 WHERE guild_id = ? AND user_id = ? AND action = ? AND active = 1",
            guild_id,
            user_id,
            action,
        )
    return n


async def set_reason(bot, guild_id: int, case_id: int, reason: str) -> None:
    await bot.db.execute(
        "UPDATE cases SET reason = ? WHERE guild_id = ? AND case_id = ?", reason, guild_id, case_id
    )


def case_embed(row) -> discord.Embed:
    label, _, color = ACTIONS.get(row["action"], (row["action"].title(), "", Colors.DEFAULT))
    emoji = emojis.get(row["action"], emojis.case)
    embed = discord.Embed(title=f"{emoji} Caso #{row['case_id']} · {label}", color=color)
    embed.add_field(name="Usuario", value=f"<@{row['user_id']}>\n`{row['user_id']}`")
    embed.add_field(name="Moderador", value=f"<@{row['mod_id']}>")
    if row["expires_at"]:
        embed.add_field(name="Expira", value=f"<t:{int(row['expires_at'])}:R>")
    embed.add_field(
        name="Razón", value=truncate(row["reason"] or "Sin razón especificada", 1000), inline=False
    )
    embed.timestamp = dt.datetime.fromtimestamp(row["created_at"], tz=dt.timezone.utc)
    if not row["active"]:
        embed.set_footer(text="Caso inactivo / eliminado")
    return embed


def case_line(row, *, show_user: bool = False) -> str:
    """Una línea resumen de un caso, para listas paginadas."""
    label = ACTIONS.get(row["action"], (row["action"].title(),))[0]
    emoji = emojis.get(row["action"], emojis.case)
    target = f" · <@{row['user_id']}>" if show_user else ""
    reason = truncate(row["reason"] or "Sin razón", 70)
    inactive = "" if row["active"] else " ~~(inactivo)~~"
    return (
        f"{emoji} `#{row['case_id']}` **{label}**{target} · "
        f"<t:{int(row['created_at'])}:R> — {reason}{inactive}"
    )


async def send_modlog(bot, guild: discord.Guild, case_id: int) -> None:
    channel_id = await bot.db.get_setting(guild.id, "modlog_channel")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    row = await get(bot, guild.id, case_id)
    if row is None:
        return
    try:
        await channel.send(embed=case_embed(row))
    except discord.HTTPException:
        pass


async def dm_user(
    bot,
    guild: discord.Guild,
    user: Any,
    action: str,
    reason: Optional[str] = None,
    *,
    duration: Optional[dt.timedelta] = None,
) -> bool:
    """Avisa por DM al sancionado (si el servidor no lo desactivó). True si se envió."""
    if not await bot.db.get_setting(guild.id, "dm_on_punish", True):
        return False
    if getattr(user, "bot", False):
        return False
    _, participle, color = ACTIONS[action]
    embed = discord.Embed(title=f"Has sido {participle} en {guild.name}", color=color)
    embed.add_field(
        name="Razón", value=truncate(reason or "Sin razón especificada", 1000), inline=False
    )
    if duration:
        embed.add_field(name="Duración", value=format_timedelta(duration))
    try:
        await user.send(embed=embed)
        return True
    except (discord.HTTPException, AttributeError):
        return False
