"""Vistas interactivas reutilizables: paginador con botones y confirmación."""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import discord

from config import Colors
from core import embeds
from core.emojis import emojis
from core.utils import truncate

log = logging.getLogger("bot.views")


def _btn_emoji(name: str, safe: bool) -> str:
    """Emoji de botón; con safe=True usa siempre el normal (reintento tras un 'Invalid emoji')."""
    return emojis.fallback(name) if safe else emojis.button(name)


def _is_emoji_error(exc: discord.HTTPException) -> bool:
    return exc.code == 50035 and "emoji" in str(exc).lower()


def make_pages(
    lines: Sequence[str],
    *,
    title: str,
    per_page: int = 10,
    color: int = Colors.DEFAULT,
    thumbnail: Optional[str] = None,
) -> List[discord.Embed]:
    """Parte una lista de líneas en embeds de `per_page` líneas cada uno."""
    lines = [truncate(line, 300) for line in lines]
    chunks = [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]
    pages = []
    for number, chunk in enumerate(chunks, 1):
        embed = discord.Embed(title=title, description="\n".join(chunk), color=color)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text=f"Página {number}/{len(chunks)} ({len(lines)} entradas)")
        pages.append(embed)
    return pages


class Paginator(discord.ui.View):
    def __init__(self, ctx, pages: List[discord.Embed], *, timeout: float = 120, safe: bool = False) -> None:
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.pages = pages
        self.index = 0
        self.message: Optional[discord.Message] = None

        self.prev_button = discord.ui.Button(emoji=_btn_emoji("prev", safe), style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(emoji=_btn_emoji("next", safe), style=discord.ButtonStyle.secondary)
        self.search_button = discord.ui.Button(emoji=_btn_emoji("search", safe), style=discord.ButtonStyle.secondary)
        self.close_button = discord.ui.Button(emoji=_btn_emoji("close", safe), style=discord.ButtonStyle.danger)
        self.prev_button.callback = self._prev
        self.next_button.callback = self._next
        self.search_button.callback = self._search
        self.close_button.callback = self._close
        # Mismo orden que Greed:  <  >  🔍  🚫(rojo)
        for button in (self.prev_button, self.next_button, self.search_button, self.close_button):
            self.add_item(button)
        self._refresh()

    @property
    def page_count(self) -> int:
        return len(self.pages)

    async def go_to(self, interaction: discord.Interaction, index: int) -> None:
        self.index = max(0, min(self.page_count - 1, index))
        await self._show(interaction)

    def _refresh(self) -> None:
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    async def _show(self, interaction: discord.Interaction) -> None:
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def _prev(self, interaction: discord.Interaction) -> None:
        self.index = max(0, self.index - 1)
        await self._show(interaction)

    async def _next(self, interaction: discord.Interaction) -> None:
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self._show(interaction)

    async def _search(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(PageJump(self))

    async def _close(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Solo quien usó el comando puede usar estos botones.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class PageJump(discord.ui.Modal, title="Ir a la página"):
    """Ventana del botón 🔍. Sirve para cualquier paginador con `page_count` y `go_to()`."""

    page = discord.ui.TextInput(label="Número de página", placeholder="1", max_length=4)

    def __init__(self, paginator) -> None:
        super().__init__()
        self.paginator = paginator
        self.page.placeholder = f"1 - {paginator.page_count}"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        total = self.paginator.page_count
        try:
            number = int(str(self.page).strip())
        except ValueError:
            return await interaction.response.send_message("Escribe un número de página.", ephemeral=True)
        if not 1 <= number <= total:
            return await interaction.response.send_message(f"La página debe estar entre 1 y {total}.", ephemeral=True)
        await self.paginator.go_to(interaction, number - 1)


async def paginate(ctx, pages: List[discord.Embed], *, always_buttons: bool = False) -> Optional[discord.Message]:
    """Envía los embeds con los botones ◀ ▶ 🔍 🚫 (o directo si solo hay una página).

    always_buttons=True muestra los botones aunque haya una sola página (como el help de Greed).
    """
    if not pages:
        return None
    if len(pages) == 1 and not always_buttons:
        return await ctx.send(embed=pages[0])
    try:
        view = Paginator(ctx, pages)
        view.message = await ctx.send(embed=pages[0], view=view)
    except discord.HTTPException as exc:
        if not _is_emoji_error(exc):
            raise
        log.warning("Discord rechazó un emoji de los botones; reintento con emojis normales. Usa `botemoji check`.")
        view = Paginator(ctx, pages, safe=True)
        view.message = await ctx.send(embed=pages[0], view=view)
    return view.message


class Confirm(discord.ui.View):
    def __init__(self, ctx, *, timeout: float = 30, safe: bool = False) -> None:
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.value: Optional[bool] = None

        yes = discord.ui.Button(
            label="Confirmar", emoji=_btn_emoji("confirm", safe), style=discord.ButtonStyle.success
        )
        no = discord.ui.Button(
            label="Cancelar", emoji=_btn_emoji("cancel", safe), style=discord.ButtonStyle.secondary
        )
        yes.callback = self._yes
        no.callback = self._no
        self.add_item(yes)
        self.add_item(no)

    async def _yes(self, interaction: discord.Interaction) -> None:
        self.value = True
        await interaction.response.defer()
        self.stop()

    async def _no(self, interaction: discord.Interaction) -> None:
        self.value = False
        await interaction.response.defer()
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Solo quien usó el comando puede responder.", ephemeral=True
            )
            return False
        return True


async def confirm(ctx, text: str, *, timeout: float = 30) -> bool:
    """Pide confirmación con botones. Devuelve True solo si el autor pulsa Confirmar."""
    try:
        view = Confirm(ctx, timeout=timeout)
        message = await ctx.send(embed=embeds.warn(ctx.author, text), view=view)
    except discord.HTTPException as exc:
        if not _is_emoji_error(exc):
            raise
        view = Confirm(ctx, timeout=timeout, safe=True)
        message = await ctx.send(embed=embeds.warn(ctx.author, text), view=view)
    await view.wait()
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    return bool(view.value)


# ----------------------------------------------------------------------
# Lista numerada con el diseño de Greed (Components V2, discord.py >= 2.6):
# contenedor con barra de color, título + miniatura, separadores, líneas "01 @rol · ID",
# pie "Página 1/4" y los botones dentro del mismo cuadro.
# ----------------------------------------------------------------------
HAS_V2 = hasattr(discord.ui, "LayoutView")

if HAS_V2:

    class ListLayout(discord.ui.LayoutView):
        def __init__(
            self,
            ctx,
            *,
            title: str,
            lines: Sequence[str],
            subtitle: Sequence[str] = (),
            thumbnail: Optional[str] = None,
            per_page: int = 10,
            color: int = Colors.TAN,
            timeout: float = 120,
            safe: bool = False,
        ) -> None:
            super().__init__(timeout=timeout)
            self.ctx = ctx
            self.title = title
            self.lines = list(lines)
            self.subtitle = list(subtitle)[:2]  # una sección admite 3 textos: título + 2
            self.thumbnail = thumbnail
            self.per_page = per_page
            self.color = color
            self.safe = safe
            self.index = 0
            self.disabled = False
            self.message: Optional[discord.Message] = None
            self._build()

        @property
        def page_count(self) -> int:
            return max(1, -(-len(self.lines) // self.per_page))

        def _buttons(self) -> List[discord.ui.Button]:
            specs = (
                ("prev", discord.ButtonStyle.secondary, self._prev, self.index <= 0),
                ("next", discord.ButtonStyle.secondary, self._next, self.index >= self.page_count - 1),
                ("search", discord.ButtonStyle.secondary, self._search, False),
                ("close", discord.ButtonStyle.danger, self._close, False),
            )
            buttons = []
            for name, style, callback, disabled in specs:
                button = discord.ui.Button(emoji=_btn_emoji(name, self.safe), style=style, disabled=disabled or self.disabled)
                button.callback = callback
                buttons.append(button)
            return buttons

        def _build(self) -> None:
            self.clear_items()
            start = self.index * self.per_page
            width = max(2, len(str(len(self.lines))))
            body = "\n".join(
                f"`{start + i + 1:0{width}d}` {line}" for i, line in enumerate(self.lines[start : start + self.per_page])
            )
            # Título + 2 líneas de texto: así el bloque llena el alto de la miniatura y no queda hueco.
            texts = [discord.ui.TextDisplay(f"## {truncate(self.title, 200)}")]
            texts += [discord.ui.TextDisplay(truncate(text, 200)) for text in self.subtitle]
            head = [discord.ui.Section(*texts, accessory=discord.ui.Thumbnail(self.thumbnail))] if self.thumbnail else texts
            self.add_item(
                discord.ui.Container(
                    *head,
                    discord.ui.Separator(),
                    discord.ui.TextDisplay(truncate(body or "Nada que mostrar.", 3500)),
                    discord.ui.Separator(),
                    discord.ui.TextDisplay(f"-# Página {self.index + 1}/{self.page_count}"),
                    discord.ui.ActionRow(*self._buttons()),
                    accent_colour=self.color,
                )
            )

        async def go_to(self, interaction: discord.Interaction, index: int) -> None:
            self.index = max(0, min(self.page_count - 1, index))
            self._build()
            await interaction.response.edit_message(view=self)

        async def _prev(self, interaction: discord.Interaction) -> None:
            await self.go_to(interaction, self.index - 1)

        async def _next(self, interaction: discord.Interaction) -> None:
            await self.go_to(interaction, self.index + 1)

        async def _search(self, interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(PageJump(self))

        async def _close(self, interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass
            self.stop()

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message(
                    "Solo quien usó el comando puede usar estos botones.", ephemeral=True
                )
                return False
            return True

        async def on_timeout(self) -> None:
            if self.message is not None:
                self.disabled = True
                self._build()
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass


async def paginate_list(
    ctx,
    *,
    title: str,
    lines: Sequence[str],
    subtitle: Sequence[str] = (),
    thumbnail: Optional[str] = None,
    per_page: int = 10,
    color: int = Colors.TAN,
) -> Optional[discord.Message]:
    """Lista numerada paginada con el diseño de Greed. Con discord.py < 2.6 cae a embeds clásicos."""
    if not lines:
        return None
    if HAS_V2:
        kwargs = dict(title=title, lines=lines, subtitle=subtitle, thumbnail=thumbnail, per_page=per_page, color=color)
        try:
            view = ListLayout(ctx, **kwargs)
            view.message = await ctx.send(view=view)
        except discord.HTTPException as exc:
            if not _is_emoji_error(exc):
                raise
            log.warning("Discord rechazó un emoji de los botones; reintento con emojis normales. Usa `botemoji check`.")
            view = ListLayout(ctx, safe=True, **kwargs)
            view.message = await ctx.send(view=view)
        return view.message
    width = max(2, len(str(len(lines))))
    numbered = [f"`{i:0{width}d}` {line}" for i, line in enumerate(lines, 1)]
    pages = make_pages(numbered, title=title, per_page=per_page, color=color, thumbnail=thumbnail)
    if subtitle:
        for page in pages:
            page.description = "\n".join(subtitle) + "\n\n" + (page.description or "")
    return await paginate(ctx, pages, always_buttons=True)
