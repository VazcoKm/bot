"""Clase base de todos los cogs.

`category` es la categoría que se ve en el comando help (varios cogs pueden compartirla).
Los cogs con category = None (help, errores, developer) no aparecen en la ayuda.
"""
from __future__ import annotations

from typing import Optional

from discord.ext import commands


class BaseCog(commands.Cog):
    category: Optional[str] = None
    guild_only: bool = True

    def __init__(self, bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx) -> bool:
        if self.guild_only and ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True
