"""Chequeos de jerarquía: evitan que alguien sancione a quien no debe.

Los mensajes siguen el estilo de Greed: "No puedes moderar a @usuario — es el dueño del servidor."
"""
from __future__ import annotations

import discord

from core.errors import BotError


def ensure_hierarchy(ctx, target: discord.Member, action: str = "moderar", *, allow_self: bool = False) -> None:
    """Lanza BotError si el autor o el bot no pueden moderar a `target`.

    `action` se conserva por compatibilidad con los comandos; el mensaje siempre dice "moderar".
    """
    guild = ctx.guild
    who = target.mention
    if target.id == ctx.author.id and not allow_self:
        raise BotError("No puedes moderarte a ti mismo.")
    if target.id == ctx.me.id:
        raise BotError("No puedo moderarme a mí mismo.")
    if target.id == guild.owner_id:
        raise BotError(f"No puedes moderar a {who} — es el dueño del servidor.")
    if target.id != ctx.author.id:
        if ctx.author.id != guild.owner_id and ctx.author.top_role <= target.top_role:
            raise BotError(f"No puedes moderar a {who} — su rol es igual o superior al tuyo.")
    if ctx.me.top_role <= target.top_role:
        raise BotError(f"No puedo moderar a {who} — mi rol más alto debe estar por encima del suyo.")


def ensure_role_manageable(ctx, role: discord.Role) -> None:
    """Lanza BotError si el autor o el bot no pueden gestionar `role`."""
    if role.is_default() or role.managed:
        raise BotError(f"No puedo gestionar {role.mention} — es @everyone o un rol de integración.")
    if role >= ctx.me.top_role:
        raise BotError(f"No puedo gestionar {role.mention} — mi rol más alto debe estar por encima.")
    if ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
        raise BotError(f"No puedes gestionar {role.mention} — está por encima de tu rol más alto.")
