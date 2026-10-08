"""Utilidad · quote: imagen de cita de un mensaje (respondiéndolo) o de un texto.

Debajo de la imagen salen tres menús, como en Greed: fuente, tema y diseño.
"""
from __future__ import annotations

import asyncio
import io
from typing import Dict, Optional

import discord
from discord.ext import commands

from core.cog import BaseCog
from core.context import Context
from core.errors import BotError
from core.quote_image import FONTS, LAYOUTS, THEMES, render_quote

TABLES = {"font": FONTS, "theme": THEMES, "layout": LAYOUTS}
PLACEHOLDERS = {"font": "Fuente", "theme": "Tema", "layout": "Diseño"}


def _label(table_key: str, value: str) -> str:
    data = TABLES[table_key][value]
    return data[0] if isinstance(data, tuple) else data["label"]


class QuoteView(discord.ui.View):
    def __init__(self, ctx: Context, avatar: Optional[bytes], text: str, name: str, handle: str) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        self.avatar, self.text, self.name, self.handle = avatar, text, name, handle
        self.state: Dict[str, str] = {"font": "poppins", "theme": "white", "layout": "wide"}
        self.message: Optional[discord.Message] = None
        self.selects: Dict[str, discord.ui.Select] = {}
        for key in ("font", "theme", "layout"):
            select = discord.ui.Select(placeholder=PLACEHOLDERS[key], options=self._options(key), min_values=1, max_values=1)
            select.callback = self._callback(key)
            self.selects[key] = select
            self.add_item(select)

    def _options(self, key: str):
        return [
            discord.SelectOption(label=_label(key, value), value=value, default=(value == self.state[key]))
            for value in TABLES[key]
        ]

    def _callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            self.state[key] = self.selects[key].values[0]
            self.selects[key].options = self._options(key)
            await interaction.response.defer()
            await interaction.edit_original_response(attachments=[await self.render()], view=self)

        return callback

    async def render(self) -> discord.File:
        png = await asyncio.to_thread(render_quote, self.avatar, self.text, self.name, self.handle, **self.state)
        return discord.File(io.BytesIO(png), filename="quote.png")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Solo quien usó el comando puede cambiar la imagen.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class UtilityQuote(BaseCog):
    category = "Utilidad"

    @commands.command(name="quote", aliases=["q"], usage="[texto]")
    @commands.bot_has_permissions(attach_files=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def quote(self, ctx: Context, *, text: Optional[str] = None):
        """Crea una imagen de cita: responde a un mensaje o escribe el texto."""
        if text:
            author, content = ctx.author, text
        else:
            reference = ctx.message.reference
            target = reference.resolved if reference else None
            if not isinstance(target, discord.Message):
                raise BotError("Debes indicar `texto` o responder a un mensaje.")
            author, content = target.author, target.clean_content
        if not content.strip():
            raise BotError("Ese mensaje no tiene texto que citar.")
        if len(content) > 600:
            raise BotError("El texto es demasiado largo (máximo **600** caracteres).")
        async with ctx.typing():
            try:
                avatar = await author.display_avatar.with_format("png").with_size(512).read()
            except (discord.HTTPException, ValueError):
                avatar = None
            view = QuoteView(ctx, avatar, content, author.display_name, author.name)
            file = await view.render()
        view.message = await ctx.send(file=file, view=view)


async def setup(bot) -> None:
    await bot.add_cog(UtilityQuote(bot))
