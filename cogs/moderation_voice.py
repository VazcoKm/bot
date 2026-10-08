"""Moderación de voz: silenciar, ensordecer, mover y desconectar miembros."""
from __future__ import annotations

from typing import Optional, Union

import discord
from discord.ext import commands

from core import cases, checks
from core.cog import BaseCog
from core.context import Context
from core.errors import BotError
from core.utils import truncate

VoiceLike = Union[discord.VoiceChannel, discord.StageChannel]


def _why(reason: Optional[str]) -> str:
    return f" — {truncate(reason, 120)}" if reason else ""


def _voice_channel(member: discord.Member) -> VoiceLike:
    if member.voice is None or member.voice.channel is None:
        raise BotError(f"**{member.name}** no está en un canal de voz.")
    return member.voice.channel


class ModVoice(BaseCog):
    """Control de miembros en canales de voz."""

    category = "Moderación"

    @commands.command(name="vcmute", usage="<miembro> [razón]")
    @commands.has_permissions(mute_members=True)
    @commands.bot_has_permissions(mute_members=True)
    async def vcmute(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Silencia el micrófono de un miembro en voz."""
        checks.ensure_hierarchy(ctx, member, "moderar")
        _voice_channel(member)
        await member.edit(mute=True, reason=cases.audit_reason(ctx.author, reason))
        await ctx.approve(f"**{member.name}** fue silenciado en voz{_why(reason)}")

    @commands.command(name="vcunmute", usage="<miembro> [razón]")
    @commands.has_permissions(mute_members=True)
    @commands.bot_has_permissions(mute_members=True)
    async def vcunmute(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Quita el silencio de micrófono a un miembro en voz."""
        _voice_channel(member)
        await member.edit(mute=False, reason=cases.audit_reason(ctx.author, reason))
        await ctx.approve(f"**{member.name}** ya puede hablar en voz.")

    @commands.command(name="vcdeafen", usage="<miembro> [razón]")
    @commands.has_permissions(deafen_members=True)
    @commands.bot_has_permissions(deafen_members=True)
    async def vcdeafen(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Ensordece a un miembro en voz."""
        checks.ensure_hierarchy(ctx, member, "moderar")
        _voice_channel(member)
        await member.edit(deafen=True, reason=cases.audit_reason(ctx.author, reason))
        await ctx.approve(f"**{member.name}** fue ensordecido en voz{_why(reason)}")

    @commands.command(name="vcundeafen", usage="<miembro> [razón]")
    @commands.has_permissions(deafen_members=True)
    @commands.bot_has_permissions(deafen_members=True)
    async def vcundeafen(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Quita el ensordecimiento a un miembro en voz."""
        _voice_channel(member)
        await member.edit(deafen=False, reason=cases.audit_reason(ctx.author, reason))
        await ctx.approve(f"**{member.name}** ya puede escuchar en voz.")

    @commands.command(name="vckick", aliases=["vcdisconnect"], usage="<miembro> [razón]")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def vckick(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Desconecta a un miembro de su canal de voz."""
        checks.ensure_hierarchy(ctx, member, "moderar")
        channel = _voice_channel(member)
        await member.move_to(None, reason=cases.audit_reason(ctx.author, reason))
        await ctx.approve(f"**{member.name}** fue desconectado de {channel.mention}{_why(reason)}")

    @commands.command(name="vcmove", usage="<miembro> <canal de voz>")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def vcmove(self, ctx: Context, member: discord.Member, channel: VoiceLike):
        """Mueve a un miembro a otro canal de voz."""
        _voice_channel(member)
        await member.move_to(channel, reason=cases.audit_reason(ctx.author, "vcmove"))
        await ctx.approve(f"**{member.name}** fue movido a {channel.mention}.")

    @commands.command(name="drag", aliases=["pull"], usage="<miembro>")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def drag(self, ctx: Context, member: discord.Member):
        """Trae a un miembro a tu canal de voz."""
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            raise BotError("Tienes que estar en un canal de voz.")
        _voice_channel(member)
        destination = ctx.author.voice.channel
        await member.move_to(destination, reason=cases.audit_reason(ctx.author, "drag"))
        await ctx.approve(f"**{member.name}** fue traído a {destination.mention}.")

    @commands.command(name="vcmoveall", usage="<canal origen> <canal destino>")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def vcmoveall(self, ctx: Context, source: VoiceLike, destination: VoiceLike):
        """Mueve a todos los miembros de un canal de voz a otro."""
        if source.id == destination.id:
            raise BotError("El canal de origen y el de destino son el mismo.")
        members = list(source.members)
        if not members:
            raise BotError(f"{source.mention} está vacío.")
        moved = 0
        for member in members:
            try:
                await member.move_to(destination, reason=cases.audit_reason(ctx.author, "vcmoveall"))
                moved += 1
            except discord.HTTPException:
                pass
        await ctx.approve(f"Se movieron **{moved}** miembros de {source.mention} a {destination.mention}.")

    @commands.command(name="vckickall", aliases=["vcclear"], usage="[canal de voz]")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def vckickall(self, ctx: Context, channel: Optional[VoiceLike] = None):
        """Desconecta a todos los miembros de un canal de voz (por defecto el tuyo)."""
        if channel is None:
            if ctx.author.voice is None or ctx.author.voice.channel is None:
                raise BotError("Indica un canal de voz o únete a uno.")
            channel = ctx.author.voice.channel
        members = list(channel.members)
        if not members:
            raise BotError(f"{channel.mention} está vacío.")
        kicked = 0
        for member in members:
            try:
                await member.move_to(None, reason=cases.audit_reason(ctx.author, "vckickall"))
                kicked += 1
            except discord.HTTPException:
                pass
        await ctx.approve(f"Se desconectaron **{kicked}** miembros de {channel.mention}.")


async def setup(bot) -> None:
    await bot.add_cog(ModVoice(bot))
