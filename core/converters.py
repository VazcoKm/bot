"""Convertidores de argumentos reutilizables."""
from __future__ import annotations

import datetime as dt
import re

from discord.ext import commands

from core.errors import BotError

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_FULL = re.compile(r"(?:\d+[smhdw])+")
_PART = re.compile(r"(\d+)([smhdw])")


class Duration(commands.Converter):
    """'30m', '2h', '1d12h', '1w' -> timedelta. 'off' / '0' -> timedelta(0)."""

    async def convert(self, ctx, argument: str) -> dt.timedelta:
        text = argument.strip().lower()
        if text in {"off", "none", "no", "0"}:
            return dt.timedelta(0)
        if not _FULL.fullmatch(text):
            raise BotError(
                f"`{argument[:30]}` no es una duración válida (ejemplos: `30m`, `2h`, `1d`, `1w`)."
            )
        seconds = sum(int(n) * _UNITS[u] for n, u in _PART.findall(text))
        if seconds > 365 * 86400:
            raise BotError("La duración máxima es de 1 año.")
        return dt.timedelta(seconds=seconds)


class FuzzyRole(commands.RoleConverter):
    """Rol por mención, ID, nombre exacto o parte del nombre (ej. 'muri' -> 'MurillokEMEPES')."""

    async def convert(self, ctx, argument: str):
        try:
            return await super().convert(ctx, argument)
        except commands.RoleNotFound:
            pass
        text = argument.strip().lower()
        roles = [r for r in ctx.guild.roles if not r.is_default()]
        for matches in (
            [r for r in roles if r.name.lower() == text],
            [r for r in roles if r.name.lower().startswith(text)],
            [r for r in roles if text in r.name.lower()],
        ):
            if matches:
                return max(matches, key=lambda r: r.position)
        raise commands.RoleNotFound(argument)
