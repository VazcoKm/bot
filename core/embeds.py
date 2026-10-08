"""Estilo de los embeds. Si quieres cambiar cómo se ve TODO el bot, edita este archivo.

Formato (como los bots tipo Bleed/Greed): una línea con emoji + mención + mensaje,
y la barra lateral del color que corresponda (éxito, error, aviso).
"""
from __future__ import annotations

from typing import Optional

import discord

from config import Colors
from core.emojis import emojis


def _line(emoji: str, user: Optional[discord.abc.User], text: str) -> str:
    body = f"{emoji} {user.mention}: {text}" if user is not None else f"{emoji} {text}"
    return body[:4096]


def custom(user: Optional[discord.abc.User], emoji: str, text: str, color: int) -> discord.Embed:
    """Embed de una línea con cualquier emoji y color."""
    return discord.Embed(description=_line(emoji, user, text), color=color)


def success(user: Optional[discord.abc.User], text: str, *, emoji: Optional[str] = None) -> discord.Embed:
    return custom(user, emoji or emojis.success, text, Colors.SUCCESS)


def error(user: Optional[discord.abc.User], text: str) -> discord.Embed:
    return custom(user, emojis.error, text, Colors.ERROR)


def warn(user: Optional[discord.abc.User], text: str) -> discord.Embed:
    return custom(user, emojis.warn, text, Colors.WARN)


def neutral(text: str, *, title: Optional[str] = None) -> discord.Embed:
    return discord.Embed(title=title, description=text[:4096], color=Colors.DEFAULT)
