"""Moderación de canales: lock, hide, slowmode, nuke y la familia purge."""
from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Callable, Optional

import discord
from discord.ext import commands

from core import cases, embeds
from core.cog import BaseCog
from core.context import Context
from core.converters import Duration
from core.errors import BotError
from core.utils import format_timedelta
from core.views import confirm

LINK_RE = re.compile(r"https?://\S+", re.I)
INVITE_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/\S+", re.I)
MAX_SLOWMODE = 21600  # 6 horas, límite de Discord


def _has_image(message: discord.Message) -> bool:
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            return True
    return any(embed.type in ("image", "gifv") for embed in message.embeds)


class ModChannels(BaseCog):
    """Control de canales y limpieza de mensajes."""

    category = "Moderación"

    # ------------------------------------------------------------------
    # Helpers lock / hide
    # ------------------------------------------------------------------
    async def _toggle_overwrite(
        self,
        channel: discord.TextChannel,
        *,
        attribute: str,
        value: bool,
        key_prefix: str,
        moderator: discord.abc.User,
        reason: Optional[str],
        already_msg: str,
        not_msg: str,
    ) -> None:
        """Pone/quita un permiso de @everyone en un canal recordando el valor previo."""
        guild = channel.guild
        everyone = guild.default_role
        overwrite = channel.overwrites_for(everyone)
        current = getattr(overwrite, attribute)
        key = f"{key_prefix}:{channel.id}"
        if value is False:  # activar el bloqueo
            if current is False:
                raise BotError(already_msg.format(channel=channel.mention))
            await self.bot.db.set_setting(guild.id, key, current)
            setattr(overwrite, attribute, False)
        else:  # revertir
            if current is not False:
                raise BotError(not_msg.format(channel=channel.mention))
            previous = await self.bot.db.get_setting(guild.id, key, None)
            setattr(overwrite, attribute, previous)
            await self.bot.db.del_setting(guild.id, key)
        await channel.set_permissions(everyone, overwrite=overwrite, reason=cases.audit_reason(moderator, reason))

    async def _lock(self, channel, locked: bool, moderator, reason=None) -> None:
        await self._toggle_overwrite(
            channel,
            attribute="send_messages",
            value=False if locked else True,
            key_prefix="lockprev",
            moderator=moderator,
            reason=reason,
            already_msg="{channel} ya está bloqueado.",
            not_msg="{channel} no está bloqueado.",
        )

    async def _hide(self, channel, hidden: bool, moderator, reason=None) -> None:
        await self._toggle_overwrite(
            channel,
            attribute="view_channel",
            value=False if hidden else True,
            key_prefix="hideprev",
            moderator=moderator,
            reason=reason,
            already_msg="{channel} ya está oculto.",
            not_msg="{channel} no está oculto.",
        )

    # ------------------------------------------------------------------
    # Lock / unlock / lockdown
    # ------------------------------------------------------------------
    @commands.command(name="lock", aliases=["l"], usage="[#canal] [razón]")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx: Context, channel: Optional[discord.TextChannel] = None, *, reason: Optional[str] = None):
        """Bloquea un canal: @everyone no puede escribir."""
        channel = channel or ctx.channel
        await self._lock(channel, True, ctx.author, reason)
        await ctx.approve(f"{channel.mention} fue **bloqueado**.")

    @commands.command(name="unlock", aliases=["ul"], usage="[#canal] [razón]")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx: Context, channel: Optional[discord.TextChannel] = None, *, reason: Optional[str] = None):
        """Desbloquea un canal y restaura sus permisos previos."""
        channel = channel or ctx.channel
        await self._lock(channel, False, ctx.author, reason)
        await ctx.approve(f"{channel.mention} fue **desbloqueado**.")

    @commands.command(name="lockdown", usage="[razón]")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def lockdown(self, ctx: Context, *, reason: Optional[str] = None):
        """Bloquea TODOS los canales de texto visibles (pide confirmación)."""
        everyone = ctx.guild.default_role
        targets = [
            c
            for c in ctx.guild.text_channels
            if c.overwrites_for(everyone).send_messages is not False and c.permissions_for(everyone).view_channel
        ]
        if not targets:
            raise BotError("No hay canales que bloquear.")
        if not await confirm(ctx, f"¿Bloquear **{len(targets)}** canales de texto?"):
            return await ctx.warn("Cancelado.")
        locked = []
        for channel in targets:
            try:
                await self._lock(channel, True, ctx.author, reason or "Lockdown")
                locked.append(channel.id)
            except (BotError, discord.HTTPException):
                pass
            await asyncio.sleep(0.4)
        await self.bot.db.set_setting(ctx.guild.id, "lockdown_channels", locked)
        await ctx.approve(f"Lockdown activo: **{len(locked)}** canales bloqueados. Usa `{ctx.clean_prefix}unlockdown` para revertir.")

    @commands.command(name="unlockdown", aliases=["unld"], usage="")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def unlockdown(self, ctx: Context):
        """Revierte el último lockdown."""
        ids = await self.bot.db.get_setting(ctx.guild.id, "lockdown_channels", [])
        if not ids:
            raise BotError("No hay ningún lockdown activo.")
        restored = 0
        for channel_id in ids:
            channel = ctx.guild.get_channel(channel_id)
            if channel is None:
                continue
            try:
                await self._lock(channel, False, ctx.author, "Unlockdown")
                restored += 1
            except (BotError, discord.HTTPException):
                pass
            await asyncio.sleep(0.4)
        await self.bot.db.del_setting(ctx.guild.id, "lockdown_channels")
        await ctx.approve(f"Lockdown terminado: **{restored}** canales desbloqueados.")

    # ------------------------------------------------------------------
    # Hide / unhide
    # ------------------------------------------------------------------
    @commands.command(name="hide", usage="[#canal] [razón]")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def hide(self, ctx: Context, channel: Optional[discord.TextChannel] = None, *, reason: Optional[str] = None):
        """Oculta un canal para @everyone."""
        channel = channel or ctx.channel
        await self._hide(channel, True, ctx.author, reason)
        await ctx.approve(f"{channel.mention} fue **ocultado**.")

    @commands.command(name="unhide", usage="[#canal] [razón]")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unhide(self, ctx: Context, channel: Optional[discord.TextChannel] = None, *, reason: Optional[str] = None):
        """Vuelve a mostrar un canal oculto."""
        channel = channel or ctx.channel
        await self._hide(channel, False, ctx.author, reason)
        await ctx.approve(f"{channel.mention} vuelve a ser **visible**.")

    # ------------------------------------------------------------------
    # Slowmode / nuke
    # ------------------------------------------------------------------
    @commands.command(name="slowmode", aliases=["slow", "sm"], usage="[duración | off] [#canal]")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(
        self,
        ctx: Context,
        duration: Optional[Duration] = None,
        channel: Optional[discord.TextChannel] = None,
    ):
        """Cambia el modo lento de un canal. Sin argumentos muestra el actual. `off` lo desactiva."""
        channel = channel or ctx.channel
        if duration is None:
            current = channel.slowmode_delay
            text = format_timedelta(current) if current else "desactivado"
            return await ctx.neutral(f"El modo lento de {channel.mention} es: **{text}**.")
        seconds = int(duration.total_seconds())
        if seconds > MAX_SLOWMODE:
            raise BotError("El máximo del modo lento es de **6 horas**.")
        await channel.edit(slowmode_delay=seconds, reason=cases.audit_reason(ctx.author, "slowmode"))
        if seconds:
            await ctx.approve(f"Modo lento de {channel.mention}: **{format_timedelta(seconds)}**.")
        else:
            await ctx.approve(f"Modo lento de {channel.mention} desactivado.")

    @commands.command(name="nuke", usage="[#canal]")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def nuke(self, ctx: Context, channel: Optional[discord.TextChannel] = None):
        """Reinicia un canal: lo clona y borra el original (se pierden los mensajes)."""
        channel = channel or ctx.channel
        if not await confirm(ctx, f"¿Reiniciar {channel.mention}? Se perderán todos sus mensajes."):
            return await ctx.warn("Cancelado.")
        position = channel.position
        reason = cases.audit_reason(ctx.author, "nuke")
        new_channel = await channel.clone(reason=reason)
        await new_channel.edit(position=position, reason=reason)
        await channel.delete(reason=reason)
        await new_channel.send(embed=embeds.success(ctx.author, "Canal reiniciado."))
        if channel.id != ctx.channel.id:
            await ctx.approve(f"{new_channel.mention} fue reiniciado.")

    # ------------------------------------------------------------------
    # Purge
    # ------------------------------------------------------------------
    async def _purge(
        self,
        ctx: Context,
        amount: int,
        check: Optional[Callable[[discord.Message], bool]] = None,
    ) -> None:
        """Borra hasta `amount` mensajes que cumplan `check` (revisa los últimos 1000).

        Ignora los mensajes fijados y los de más de 14 días (Discord no permite borrado masivo).
        """
        if not 1 <= amount <= 1000:
            raise BotError("La cantidad debe estar entre **1** y **1000**.")
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        matched = 0

        def predicate(message: discord.Message) -> bool:
            nonlocal matched
            if matched >= amount or message.pinned:
                return False
            if check is not None and not check(message):
                return False
            matched += 1
            return True

        cutoff = discord.utils.utcnow() - dt.timedelta(days=13, hours=22)
        deleted = await ctx.channel.purge(
            limit=amount if check is None else 1000,
            check=predicate,
            after=cutoff,
            oldest_first=False,
            bulk=True,
            reason=cases.audit_reason(ctx.author, "purge"),
        )
        await ctx.approve(f"Se eliminaron **{len(deleted)}** mensajes.", delete_after=5)

    @commands.group(name="purge", aliases=["clear", "c", "p"], invoke_without_command=True, usage="<cantidad>")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx: Context, amount: int):
        """Borra los últimos N mensajes del canal (máx. 1000). Subcomandos para filtrar."""
        await self._purge(ctx, amount)

    @purge.command(name="bots", usage="[cantidad]")
    async def purge_bots(self, ctx: Context, amount: int = 100):
        """Borra mensajes de bots."""
        await self._purge(ctx, amount, lambda m: m.author.bot)

    @purge.command(name="humans", usage="[cantidad]")
    async def purge_humans(self, ctx: Context, amount: int = 100):
        """Borra mensajes de personas (no bots)."""
        await self._purge(ctx, amount, lambda m: not m.author.bot)

    @purge.command(name="user", aliases=["member"], usage="<usuario> [cantidad]")
    async def purge_user(self, ctx: Context, user: discord.User, amount: int = 100):
        """Borra mensajes de un usuario concreto."""
        await self._purge(ctx, amount, lambda m: m.author.id == user.id)

    @purge.command(name="links", usage="[cantidad]")
    async def purge_links(self, ctx: Context, amount: int = 100):
        """Borra mensajes que contienen enlaces."""
        await self._purge(ctx, amount, lambda m: bool(LINK_RE.search(m.content)))

    @purge.command(name="invites", usage="[cantidad]")
    async def purge_invites(self, ctx: Context, amount: int = 100):
        """Borra mensajes con invitaciones de Discord."""
        await self._purge(ctx, amount, lambda m: bool(INVITE_RE.search(m.content)))

    @purge.command(name="images", aliases=["imgs"], usage="[cantidad]")
    async def purge_images(self, ctx: Context, amount: int = 100):
        """Borra mensajes con imágenes."""
        await self._purge(ctx, amount, _has_image)

    @purge.command(name="attachments", aliases=["files"], usage="[cantidad]")
    async def purge_attachments(self, ctx: Context, amount: int = 100):
        """Borra mensajes con archivos adjuntos."""
        await self._purge(ctx, amount, lambda m: bool(m.attachments))

    @purge.command(name="embeds", usage="[cantidad]")
    async def purge_embeds(self, ctx: Context, amount: int = 100):
        """Borra mensajes con embeds."""
        await self._purge(ctx, amount, lambda m: bool(m.embeds))

    @purge.command(name="mentions", usage="[cantidad]")
    async def purge_mentions(self, ctx: Context, amount: int = 100):
        """Borra mensajes que mencionan a alguien."""
        await self._purge(ctx, amount, lambda m: bool(m.mentions or m.role_mentions or m.mention_everyone))

    @purge.command(name="contains", usage="<cantidad> <texto>")
    async def purge_contains(self, ctx: Context, amount: int, *, text: str):
        """Borra mensajes que contienen un texto."""
        needle = text.lower()
        await self._purge(ctx, amount, lambda m: needle in m.content.lower())

    @purge.command(name="startswith", usage="<cantidad> <texto>")
    async def purge_startswith(self, ctx: Context, amount: int, *, text: str):
        """Borra mensajes que empiezan con un texto."""
        needle = text.lower()
        await self._purge(ctx, amount, lambda m: m.content.lower().startswith(needle))

    @purge.command(name="endswith", usage="<cantidad> <texto>")
    async def purge_endswith(self, ctx: Context, amount: int, *, text: str):
        """Borra mensajes que terminan con un texto."""
        needle = text.lower()
        await self._purge(ctx, amount, lambda m: m.content.lower().endswith(needle))

    @commands.command(name="clean", aliases=["cleanup"], usage="[cantidad]")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def clean(self, ctx: Context, amount: int = 50):
        """Borra los mensajes del bot y los comandos que lo invocaron."""
        prefix = ctx.prefix or ""
        await self._purge(
            ctx,
            amount,
            lambda m: m.author.id == ctx.me.id or (bool(prefix) and m.content.startswith(prefix)),
        )


async def setup(bot) -> None:
    await bot.add_cog(ModChannels(bot))
