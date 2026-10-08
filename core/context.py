"""Context propio: añade ctx.approve / ctx.deny / ctx.warn / ctx.neutral."""
from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands

from config import Colors
from core import embeds


class Context(commands.Context):
    async def approve(self, text: str, *, emoji: Optional[str] = None, **kwargs) -> discord.Message:
        """Embed verde de éxito (con `emoji=` puedes cambiar el icono, ej. emojis.plus)."""
        return await self.send(embed=embeds.success(self.author, text, emoji=emoji), **kwargs)

    async def note(self, emoji: str, text: str, **kwargs) -> discord.Message:
        """Embed gris de una línea con el emoji que quieras (ej. el 'bienvenido de vuelta' del AFK)."""
        return await self.send(embed=embeds.custom(self.author, emoji, text, Colors.DEFAULT), **kwargs)

    async def deny(self, text: str, **kwargs) -> discord.Message:
        """Embed rojo de error."""
        return await self.send(embed=embeds.error(self.author, text), **kwargs)

    async def warn(self, text: str, **kwargs) -> discord.Message:
        """Embed amarillo de aviso."""
        return await self.send(embed=embeds.warn(self.author, text), **kwargs)

    async def neutral(self, text: str, *, title: Optional[str] = None, **kwargs) -> discord.Message:
        """Embed neutro (sin emoji ni mención)."""
        return await self.send(embed=embeds.neutral(text, title=title), **kwargs)
