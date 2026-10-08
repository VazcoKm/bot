"""Utilidad · bot: latencia, tiempo activo, estadísticas e invitación."""
from __future__ import annotations

import platform
import time

import discord
from discord.ext import commands

from config import BOT_NAME, Colors
from core.cog import BaseCog
from core.context import Context
from core.utils import format_timedelta


class UtilityBot(BaseCog):
    """Información sobre el propio bot."""

    category = "Utilidad"
    guild_only = False

    @commands.command(name="ping", aliases=["latency"])
    async def ping(self, ctx: Context):
        """Latencia del bot: gateway, mensaje y base de datos."""
        gateway = ctx.bot.latency * 1000
        message = max(0.0, (discord.utils.utcnow() - ctx.message.created_at).total_seconds() * 1000)
        started = time.perf_counter()
        await ctx.bot.db.fetchone("SELECT 1")
        database = (time.perf_counter() - started) * 1000
        await ctx.approve(f"Gateway **{gateway:.0f}ms** · mensaje **{message:.0f}ms** · base de datos **{database:.1f}ms**")

    @commands.command(name="uptime")
    async def uptime(self, ctx: Context):
        """Cuánto tiempo lleva encendido el bot."""
        seconds = time.time() - getattr(ctx.bot, "started_at", time.time())
        await ctx.neutral(f"Encendido desde <t:{int(ctx.bot.started_at)}:R> · **{format_timedelta(seconds)}** activo.")

    @commands.command(name="botinfo", aliases=["about", "stats"])
    async def botinfo(self, ctx: Context):
        """Estadísticas del bot: servidores, usuarios, comandos y versiones."""
        bot = ctx.bot
        users = sum(g.member_count or 0 for g in bot.guilds)
        commands_total = sum(1 for c in bot.walk_commands() if not c.hidden)
        embed = discord.Embed(title=BOT_NAME, color=Colors.DEFAULT)
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.add_field(name="Servidores", value=str(len(bot.guilds)))
        embed.add_field(name="Usuarios", value=str(users))
        embed.add_field(name="Comandos", value=str(commands_total))
        embed.add_field(name="Latencia", value=f"{bot.latency * 1000:.0f}ms")
        embed.add_field(name="Activo", value=format_timedelta(time.time() - bot.started_at))
        embed.add_field(name="Versiones", value=f"Python {platform.python_version()} · discord.py {discord.__version__}")
        await ctx.send(embed=embed)

    @commands.command(name="invite", aliases=["inv"])
    async def invite(self, ctx: Context):
        """Enlace para invitar al bot a otro servidor."""
        url = discord.utils.oauth_url(
            ctx.bot.user.id,
            permissions=discord.Permissions(administrator=True),
            scopes=("bot", "applications.commands"),
        )
        await ctx.neutral(f"[Invitar a {BOT_NAME}]({url})")


async def setup(bot) -> None:
    await bot.add_cog(UtilityBot(bot))
