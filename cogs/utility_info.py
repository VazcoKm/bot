"""Utilidad · información: usuarios, servidor, roles, canales, emojis y consultas."""
from __future__ import annotations

import colorsys
import random
import unicodedata
from typing import List, Optional

import discord
from discord.ext import commands

from config import Colors
from core.cog import BaseCog
from core.context import Context
from core.converters import FuzzyRole
from core.errors import BotError
from core.utils import perm_name, truncate
from core.views import make_pages, paginate, paginate_list

KEY_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_messages",
    "manage_webhooks", "kick_members", "ban_members", "moderate_members", "mention_everyone",
)
CHANNEL_KINDS = {
    discord.ChannelType.text: "texto", discord.ChannelType.voice: "voz",
    discord.ChannelType.category: "categoría", discord.ChannelType.stage_voice: "escenario",
    discord.ChannelType.forum: "foro", discord.ChannelType.news: "anuncios",
}


def _both(when) -> str:
    return f"{discord.utils.format_dt(when, 'F')}\n({discord.utils.format_dt(when, 'R')})"


def _asset_url(asset: discord.Asset, size: int = 1024) -> str:
    try:
        return asset.with_size(size).url
    except ValueError:
        return asset.url


def _asset_embed(title: str, asset: discord.Asset) -> discord.Embed:
    embed = discord.Embed(title=title, color=Colors.GRAY)
    embed.set_image(url=_asset_url(asset))
    return embed


def _stamp(when) -> str:
    """'> 7 de agosto de 2026 (hace 2 meses)' con timestamps de Discord (cita con barra gris)."""
    return f"> {discord.utils.format_dt(when, 'D')} ({discord.utils.format_dt(when, 'R')})"


def _block(*pairs) -> str:
    """Líneas en cita con el valor en código: '> Texto: `1`'."""
    return "\n".join(f"> {label}: {value}" for label, value in pairs)


def _join_position(guild: discord.Guild, member: discord.Member) -> Optional[int]:
    ordered = sorted((m for m in guild.members if m.joined_at), key=lambda m: m.joined_at)
    return ordered.index(member) + 1 if member in ordered else None


_VERIFY = {"none": "ninguna", "low": "baja", "medium": "media", "high": "alta", "highest": "máxima"}
_MFA = {"disabled": "desactivado", "require_2fa": "requerido"}


def parse_color(text: str) -> discord.Color:
    """'#ff0000', 'ff0000', '0xff0000' o 'rgb(255, 0, 0)' -> discord.Color."""
    value = text.strip()
    for candidate in (value, f"#{value}"):
        try:
            return discord.Color.from_str(candidate)
        except (ValueError, TypeError):
            continue
    raise BotError(f"`{truncate(text, 30)}` no es un color válido (ejemplos: `#ff0000`, `ff0000`, `rgb(255, 0, 0)`).")


def color_embed(color: discord.Color) -> discord.Embed:
    r, g, b = color.r, color.g, color.b
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    embed = discord.Embed(title=f"Color #{r:02X}{g:02X}{b:02X}", color=color)
    embed.add_field(name="RGB", value=f"`{r}, {g}, {b}`")
    embed.add_field(name="HSV", value=f"`{round(h * 360)}°, {round(s * 100)}%, {round(v * 100)}%`")
    embed.add_field(name="Entero", value=f"`{color.value}`")
    return embed


class UtilityInfo(BaseCog):
    """Información de usuarios, servidor, roles, canales y emojis."""

    category = "Utilidad"

    # ------------------------------------------------------------------
    # Avatares y banners
    # ------------------------------------------------------------------
    @commands.command(name="avatar", aliases=["av", "pfp"], usage="[usuario]")
    async def avatar(self, ctx: Context, user: Optional[discord.User] = None):
        """Muestra el avatar global de un usuario."""
        user = user or ctx.author
        asset = user.avatar or user.default_avatar
        await ctx.send(embed=_asset_embed(f"Avatar de {user.display_name}", asset))

    @commands.command(name="serveravatar", aliases=["sav", "guildavatar"], usage="[miembro]")
    async def serveravatar(self, ctx: Context, member: Optional[discord.Member] = None):
        """Muestra el avatar de servidor de un miembro (si tiene uno)."""
        member = member or ctx.author
        if member.guild_avatar is None:
            raise BotError(f"**{member.name}** no tiene un avatar de servidor.")
        await ctx.send(embed=_asset_embed(f"Avatar de servidor de {member.display_name}", member.guild_avatar))

    @commands.command(name="banner", aliases=["userbanner"], usage="[usuario]")
    async def banner(self, ctx: Context, user: Optional[discord.User] = None):
        """Muestra el banner de perfil de un usuario."""
        user = user or ctx.author
        fetched = await ctx.bot.fetch_user(user.id)  # el banner solo viene con fetch
        if fetched.banner is None:
            raise BotError(f"**{user.name}** no tiene banner.")
        await ctx.send(embed=_asset_embed(f"Banner de {user.display_name}", fetched.banner))

    # ------------------------------------------------------------------
    # Grupo guild (como en Greed): sin subcomando muestra la ayuda paginada
    # ------------------------------------------------------------------
    @commands.group(name="guild", aliases=["server", "g"], invoke_without_command=True)
    async def guild(self, ctx: Context):
        """Información y recursos del servidor."""
        await self.bot.get_cog("Help").show(ctx, ctx.command)

    async def _guild_asset(self, ctx: Context, server: Optional[discord.Guild], attribute: str, label: str) -> None:
        target = server or ctx.guild
        asset = getattr(target, attribute)
        if asset is None:
            raise BotError(f"**{target.name}** no tiene {label}.")
        await ctx.send(embed=_asset_embed(f"{label.capitalize()} de {target.name}", asset))

    @guild.command(name="icon", usage="[servidor]")
    async def guild_icon(self, ctx: Context, server: Optional[discord.Guild] = None):
        """Muestra el icono del servidor."""
        await self._guild_asset(ctx, server, "icon", "icono")

    @guild.command(name="banner", usage="[servidor]")
    async def guild_banner(self, ctx: Context, server: Optional[discord.Guild] = None):
        """Muestra el banner del servidor."""
        await self._guild_asset(ctx, server, "banner", "banner")

    @guild.command(name="splash", usage="[servidor]")
    async def guild_splash(self, ctx: Context, server: Optional[discord.Guild] = None):
        """Muestra la imagen de invitación (splash) del servidor."""
        await self._guild_asset(ctx, server, "splash", "splash de invitación")

    @guild.command(name="stats")
    async def guild_stats(self, ctx: Context):
        """Estadísticas rápidas de miembros y contenido del servidor."""
        g = ctx.guild
        bots = sum(1 for m in g.members if m.bot)
        text = _block(
            ("Miembros", f"`{g.member_count}`"), ("Personas", f"`{g.member_count - bots}`"), ("Bots", f"`{bots}`"),
            ("Boosters", f"`{len(g.premium_subscribers)}`"), ("Canales", f"`{len(g.channels)}`"),
            ("Roles", f"`{len(g.roles)}`"), ("Emojis", f"`{len(g.emojis)}`"), ("Stickers", f"`{len(g.stickers)}`"),
        )
        await ctx.neutral(text, title=g.name)

    # ------------------------------------------------------------------
    # Usuarios
    # ------------------------------------------------------------------
    @commands.command(name="userinfo", aliases=["ui", "whois", "user", "i"], usage="[usuario]")
    async def userinfo(self, ctx: Context, user: Optional[discord.User] = None):
        """Información de un usuario (acepta mención, ID o nombre)."""
        user = user or ctx.author
        member = ctx.guild.get_member(user.id)
        embed = discord.Embed(color=Colors.GRAY)
        embed.set_author(name=f"{user.display_name} (@{user.name})", icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Creada", value=_stamp(user.created_at), inline=False)
        footer = f"ID: {user.id}"
        if member is not None:
            if member.joined_at:
                embed.add_field(name="Se unió", value=_stamp(member.joined_at), inline=False)
            roles = [r.mention for r in reversed(member.roles) if not r.is_default()]
            shown = ", ".join(roles[:20]) + (f" … (+{len(roles) - 20})" if len(roles) > 20 else "")
            embed.add_field(name=f"Roles ({len(roles)})", value=shown or "Ninguno", inline=False)
            position = _join_position(ctx.guild, member)
            if position:
                footer += f" • Posición de ingreso: {position}"
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    @commands.command(name="joined", usage="[miembro]")
    async def joined(self, ctx: Context, member: Optional[discord.Member] = None):
        """Cuándo se unió un miembro al servidor."""
        member = member or ctx.author
        if member.joined_at is None:
            raise BotError("No tengo la fecha de ingreso de ese miembro.")
        await ctx.neutral(f"**{member.name}** se unió {_both(member.joined_at).replace(chr(10), ' ')}")

    @commands.command(name="created", aliases=["age"], usage="[usuario]")
    async def created(self, ctx: Context, user: Optional[discord.User] = None):
        """Cuándo se creó la cuenta de un usuario."""
        user = user or ctx.author
        await ctx.neutral(f"La cuenta de **{user.name}** se creó {_both(user.created_at).replace(chr(10), ' ')}")

    @commands.command(name="joinpos", aliases=["jp"], usage="[miembro]")
    async def joinpos(self, ctx: Context, member: Optional[discord.Member] = None):
        """Posición de ingreso de un miembro (1 = el primero en unirse)."""
        member = member or ctx.author
        ordered = sorted((m for m in ctx.guild.members if m.joined_at), key=lambda m: m.joined_at)
        try:
            position = ordered.index(member) + 1
        except ValueError:
            raise BotError("No pude calcular la posición de ese miembro.")
        await ctx.neutral(f"**{member.name}** fue el miembro **#{position}** de **{len(ordered)}** en unirse.")

    @commands.command(name="newest", aliases=["newmembers"], usage="[cantidad]")
    async def newest(self, ctx: Context, amount: int = 10):
        """Los miembros que se unieron más recientemente (máx. 25)."""
        amount = max(1, min(amount, 25))
        members = sorted((m for m in ctx.guild.members if m.joined_at), key=lambda m: m.joined_at, reverse=True)[:amount]
        lines = [f"`{i}.` {m.mention} · {discord.utils.format_dt(m.joined_at, 'R')}" for i, m in enumerate(members, 1)]
        await ctx.neutral("\n".join(lines) or "Sin datos.", title=f"Miembros más nuevos ({len(lines)})")

    @commands.command(name="oldest", aliases=["oldmembers"], usage="[cantidad]")
    async def oldest(self, ctx: Context, amount: int = 10):
        """Los miembros que llevan más tiempo en el servidor (máx. 25)."""
        amount = max(1, min(amount, 25))
        members = sorted((m for m in ctx.guild.members if m.joined_at), key=lambda m: m.joined_at)[:amount]
        lines = [f"`{i}.` {m.mention} · {discord.utils.format_dt(m.joined_at, 'R')}" for i, m in enumerate(members, 1)]
        await ctx.neutral("\n".join(lines) or "Sin datos.", title=f"Miembros más antiguos ({len(lines)})")

    @commands.command(name="permissions", aliases=["perms"], usage="[miembro]")
    async def permissions(self, ctx: Context, member: Optional[discord.Member] = None):
        """Los permisos que tiene un miembro en este canal."""
        member = member or ctx.author
        perms = ctx.channel.permissions_for(member)
        if perms.administrator:
            text = "**Administrador** — tiene todos los permisos."
        else:
            granted = [f"`{perm_name(name)}`" for name, value in perms if value]
            text = ", ".join(granted) or "Ninguno."
        await ctx.neutral(truncate(text, 4000), title=f"Permisos de {member.name} en #{ctx.channel}")

    @commands.command(name="lookup", aliases=["fetchuser"], usage="<ID de usuario>")
    async def lookup(self, ctx: Context, user_id: int):
        """Busca a cualquier usuario de Discord por su ID, aunque no esté en el servidor."""
        try:
            user = await ctx.bot.fetch_user(user_id)
        except discord.NotFound:
            raise BotError(f"No existe ningún usuario con el ID `{user_id}`.", kind="error")
        embed = discord.Embed(color=user.accent_color or Colors.DEFAULT)
        embed.set_author(name=f"{user} · {user.id}", icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Cuenta creada", value=_both(user.created_at))
        embed.add_field(name="¿Bot?", value="Sí" if user.bot else "No")
        embed.add_field(name="En este servidor", value="Sí" if ctx.guild.get_member(user.id) else "No")
        if user.banner:
            embed.set_image(url=_asset_url(user.banner))
        await ctx.send(embed=embed)

    @commands.command(name="snowflake", aliases=["sf", "id"], usage="<ID>")
    async def snowflake(self, ctx: Context, number: int):
        """Decodifica cualquier ID de Discord: fecha de creación y datos internos."""
        if number < 4194304:
            raise BotError("Ese número no parece un ID de Discord.")
        when = discord.utils.snowflake_time(number)
        embed = discord.Embed(title=f"ID {number}", color=Colors.DEFAULT)
        embed.add_field(name="Creado", value=_both(when))
        embed.add_field(name="Timestamp", value=f"`{int(when.timestamp())}`")
        embed.add_field(name="Worker / proceso / incremento", value=f"`{(number >> 17) & 31} / {(number >> 12) & 31} / {number & 4095}`", inline=False)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Servidor
    # ------------------------------------------------------------------
    @commands.command(name="serverinfo", aliases=["si", "guildinfo", "sinfo"])
    async def serverinfo(self, ctx: Context):
        """Información general del servidor: conteos, boosts, diseño y sistema."""
        g = ctx.guild
        owner = g.owner or g.get_member(g.owner_id)
        embed = discord.Embed(description=g.description or None, color=Colors.TAN)
        embed.set_author(
            name=f"dueño: {owner.name if owner else 'desconocido'} — {g.owner_id}",
            icon_url=owner.display_avatar.url if owner else None,
        )
        if g.icon:
            embed.set_thumbnail(url=_asset_url(g.icon, 256))
        none = "`ninguno`"
        vanity = "`N/A`"
        if "VANITY_URL" in g.features:
            try:
                invite = await g.vanity_invite()
                vanity = f"`{invite.code}`" if invite else vanity
            except discord.HTTPException:
                pass
        counts_total = len(g.stickers) + len(g.emojis) + len(g.roles)
        embed.add_field(name="Creado", value=_stamp(g.created_at), inline=False)
        embed.add_field(
            name=f"Conteos ({counts_total})",
            value=_block(("Stickers", f"`{len(g.stickers)}`"), ("Emojis", f"`{len(g.emojis)}`"), ("Roles", f"`{len(g.roles)}`")),
        )
        embed.add_field(
            name=f"Canales ({len(g.channels)})",
            value=_block(("Categorías", f"`{len(g.categories)}`"), ("Texto", f"`{len(g.text_channels)}`"), ("Voz", f"`{len(g.voice_channels)}`")),
        )
        embed.add_field(
            name="Miembros",
            value=_block(("Total", f"`{g.member_count}`"), ("Boosters", f"`{len(g.premium_subscribers)}`")),
        )
        embed.add_field(
            name="Boosts",
            value=_block(("Nivel", f"`{g.premium_tier}`"), ("Boosts", f"`{g.premium_subscription_count}`"), ("Boosters", f"`{len(g.premium_subscribers)}`")),
        )
        embed.add_field(
            name="Diseño",
            value=_block(
                ("Icono", f"[ver]({_asset_url(g.icon)})" if g.icon else none),
                ("Banner", f"[ver]({_asset_url(g.banner)})" if g.banner else none),
                ("Splash", f"[ver]({_asset_url(g.splash)})" if g.splash else none),
            ),
        )
        verification = _VERIFY.get(str(g.verification_level), str(g.verification_level))
        mfa = _MFA.get(str(g.mfa_level), str(g.mfa_level))
        embed.add_field(
            name="Sistema",
            value=_block(("Verificación", f"`{verification}`"), ("Nivel MFA", f"`{mfa}`"), ("Vanity", vanity)),
        )
        embed.set_footer(text=f"ID: {g.id}")
        await ctx.send(embed=embed)

    @commands.command(name="membercount", aliases=["mc", "members"])
    async def membercount(self, ctx: Context):
        """Cuántos miembros tiene el servidor (personas y bots)."""
        total = ctx.guild.member_count
        bots = sum(1 for m in ctx.guild.members if m.bot)
        await ctx.neutral(f"**{total}** miembros · **{total - bots}** personas · **{bots}** bots", title=ctx.guild.name)

    @commands.command(name="roles", aliases=["rolelist"])
    async def roles(self, ctx: Context):
        """Lista los roles del servidor con su ID, de mayor a menor jerarquía."""
        roles = [r for r in reversed(ctx.guild.roles) if not r.is_default()]
        if not roles:
            raise BotError("Este servidor no tiene roles.")
        await paginate_list(
            ctx,
            title=f"Roles en {ctx.guild.name}",
            lines=[f"{r.mention} · `{r.id}`" for r in roles],
            subtitle=[f"**{len(roles)}** roles", "-# De mayor a menor jerarquía"],
            thumbnail=_asset_url(ctx.guild.icon, 256) if ctx.guild.icon else None,
        )

    @commands.command(name="roleinfo", aliases=["ri"], usage="<rol>")
    async def roleinfo(self, ctx: Context, *, role: FuzzyRole):
        """Información de un rol: color, posición, miembros y permisos clave."""
        embed = discord.Embed(title=role.name, color=role.color if role.color.value else Colors.DEFAULT)
        embed.add_field(name="ID", value=f"`{role.id}`")
        embed.add_field(name="Color", value=f"`{role.color}`")
        embed.add_field(name="Posición", value=str(role.position))
        embed.add_field(name="Miembros", value=str(len(role.members)))
        embed.add_field(name="Creado", value=discord.utils.format_dt(role.created_at, "R"))
        flags = [name for name, on in (("Separado", role.hoist), ("Mencionable", role.mentionable), ("Gestionado", role.managed)) if on]
        embed.add_field(name="Opciones", value=", ".join(flags) or "Ninguna")
        key = [f"`{perm_name(p)}`" for p in KEY_PERMS if getattr(role.permissions, p)]
        embed.add_field(name="Permisos clave", value=", ".join(key) or "Ninguno", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="inrole", aliases=["rolemembers"], usage="<rol>")
    async def inrole(self, ctx: Context, *, role: FuzzyRole):
        """Lista los miembros que tienen un rol."""
        lines = [f"{m.mention} (`{m.id}`)" for m in role.members]
        if not lines:
            raise BotError(f"Nadie tiene el rol {role.mention}.")
        await paginate(ctx, make_pages(lines, title=f"{role.name} ({len(lines)})"))

    @commands.command(name="bots", aliases=["botlist"])
    async def bots(self, ctx: Context):
        """Lista los bots del servidor."""
        lines = [f"{m.mention} (`{m.id}`)" for m in ctx.guild.members if m.bot]
        if not lines:
            raise BotError("No hay bots en este servidor.")
        await paginate(ctx, make_pages(lines, title=f"Bots ({len(lines)})"))

    @commands.command(name="admins", aliases=["administrators"])
    async def admins(self, ctx: Context):
        """Lista las personas con permiso de administrador."""
        lines = [f"{m.mention} · {m.top_role.mention}" for m in ctx.guild.members if not m.bot and m.guild_permissions.administrator]
        if not lines:
            raise BotError("No encontré administradores.")
        await paginate(ctx, make_pages(lines, title=f"Administradores ({len(lines)})"))

    @commands.command(name="boosters", aliases=["boosts"])
    async def boosters(self, ctx: Context):
        """Lista a quienes están impulsando (boost) el servidor."""
        boosters = sorted(ctx.guild.premium_subscribers, key=lambda m: m.premium_since or m.joined_at)
        if not boosters:
            raise BotError("Nadie está impulsando este servidor.")
        lines = [f"{m.mention} · desde {discord.utils.format_dt(m.premium_since, 'R')}" for m in boosters if m.premium_since]
        await paginate(ctx, make_pages(lines, title=f"Boosters ({len(lines)})"))

    # ------------------------------------------------------------------
    # Canales y emojis
    # ------------------------------------------------------------------
    @commands.command(name="channelinfo", aliases=["ci"], usage="[canal]")
    async def channelinfo(self, ctx: Context, channel: Optional[discord.abc.GuildChannel] = None):
        """Información de un canal (por defecto el actual)."""
        channel = channel or ctx.channel
        kind = CHANNEL_KINDS.get(channel.type, str(channel.type))
        embed = discord.Embed(title=f"#{channel.name}", color=Colors.DEFAULT)
        embed.add_field(name="ID", value=f"`{channel.id}`")
        embed.add_field(name="Tipo", value=kind)
        embed.add_field(name="Creado", value=discord.utils.format_dt(channel.created_at, "R"))
        if getattr(channel, "category", None):
            embed.add_field(name="Categoría", value=channel.category.name)
        if isinstance(channel, discord.TextChannel):
            embed.add_field(name="Modo lento", value=f"{channel.slowmode_delay}s" if channel.slowmode_delay else "Desactivado")
            embed.add_field(name="NSFW", value="Sí" if channel.is_nsfw() else "No")
            if channel.topic:
                embed.add_field(name="Tema", value=truncate(channel.topic, 500), inline=False)
        elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            embed.add_field(name="Bitrate", value=f"{channel.bitrate // 1000} kbps")
            embed.add_field(name="Límite", value=str(channel.user_limit or "Sin límite"))
            embed.add_field(name="Conectados", value=str(len(channel.members)))
        await ctx.send(embed=embed)

    @commands.command(name="channels", aliases=["channellist"])
    async def channels(self, ctx: Context):
        """Lista los canales del servidor con su tipo."""
        lines = []
        for channel in ctx.guild.channels:
            kind = CHANNEL_KINDS.get(channel.type, str(channel.type))
            label = f"**{channel.name}**" if isinstance(channel, discord.CategoryChannel) else channel.mention
            lines.append(f"`{kind}` {label}")
        await paginate(ctx, make_pages(lines, title=f"Canales ({len(lines)})", per_page=15))

    @commands.command(name="voicestats", aliases=["vcstats"])
    async def voicestats(self, ctx: Context):
        """Cuántas personas hay ahora mismo en canales de voz."""
        channels = [*ctx.guild.voice_channels, *ctx.guild.stage_channels]
        busy = [(c, len(c.members)) for c in channels if c.members]
        total = sum(n for _, n in busy)
        if not total:
            return await ctx.warn("No hay nadie en canales de voz.")
        lines = [f"{c.mention} · **{n}**" for c, n in sorted(busy, key=lambda item: -item[1])]
        await ctx.neutral("\n".join(lines), title=f"En voz: {total}")

    @commands.command(name="emojis", aliases=["emojilist"])
    async def emojis(self, ctx: Context):
        """Lista los emojis del servidor."""
        lines = [f"{e} `:{e.name}:` · `{e.id}`" for e in ctx.guild.emojis]
        if not lines:
            raise BotError("Este servidor no tiene emojis personalizados.")
        await paginate(ctx, make_pages(lines, title=f"Emojis ({len(lines)})", per_page=15))

    @commands.command(name="stickers", aliases=["stickerlist"])
    async def stickers(self, ctx: Context):
        """Lista los stickers del servidor."""
        lines = [f"**{s.name}** · `{s.id}`" for s in ctx.guild.stickers]
        if not lines:
            raise BotError("Este servidor no tiene stickers.")
        await paginate(ctx, make_pages(lines, title=f"Stickers ({len(lines)})"))

    @commands.command(name="emojiinfo", aliases=["ei"], usage="<emoji>")
    async def emojiinfo(self, ctx: Context, emoji: discord.PartialEmoji):
        """Información de un emoji personalizado."""
        if emoji.id is None:
            raise BotError("Solo funciona con emojis personalizados de servidor.")
        embed = discord.Embed(title=f":{emoji.name}:", color=Colors.DEFAULT)
        embed.set_thumbnail(url=emoji.url)
        embed.add_field(name="ID", value=f"`{emoji.id}`")
        embed.add_field(name="Animado", value="Sí" if emoji.animated else "No")
        embed.add_field(name="Creado", value=discord.utils.format_dt(discord.utils.snowflake_time(emoji.id), "R"))
        known = ctx.bot.get_emoji(emoji.id)
        if known is not None:
            embed.add_field(name="Servidor", value=known.guild.name)
        embed.add_field(name="URL", value=f"[abrir]({emoji.url})")
        await ctx.send(embed=embed)

    @commands.command(name="enlarge", aliases=["jumbo", "bigemoji"], usage="<emoji>")
    async def enlarge(self, ctx: Context, emoji: discord.PartialEmoji):
        """Muestra un emoji personalizado en grande."""
        if emoji.id is None:
            raise BotError("Solo funciona con emojis personalizados de servidor.")
        embed = discord.Embed(title=f":{emoji.name}:", color=Colors.DEFAULT)
        embed.set_image(url=emoji.url)
        await ctx.send(embed=embed)

    @commands.command(name="inviteinfo", aliases=["invinfo"], usage="<invitación>")
    async def inviteinfo(self, ctx: Context, invite: str):
        """Información de una invitación (código o enlace)."""
        code = invite.strip().rstrip("/").split("/")[-1]
        try:
            info = await ctx.bot.fetch_invite(code, with_counts=True)
        except discord.NotFound:
            raise BotError("Esa invitación no existe o expiró.", kind="error")
        embed = discord.Embed(title=info.guild.name if info.guild else "Invitación", color=Colors.DEFAULT)
        embed.add_field(name="Código", value=f"`{info.code}`")
        if info.channel:
            embed.add_field(name="Canal", value=f"#{info.channel.name}")
        if info.inviter:
            embed.add_field(name="Creada por", value=str(info.inviter))
        if info.approximate_member_count is not None:
            embed.add_field(name="Miembros", value=f"{info.approximate_member_count} ({info.approximate_presence_count} en línea)")
        if info.expires_at:
            embed.add_field(name="Expira", value=discord.utils.format_dt(info.expires_at, "R"))
        await ctx.send(embed=embed)

    @commands.command(name="firstmessage", aliases=["first"], usage="[#canal]")
    async def firstmessage(self, ctx: Context, channel: Optional[discord.TextChannel] = None):
        """Enlace al primer mensaje de un canal."""
        channel = channel or ctx.channel
        async for message in channel.history(limit=1, oldest_first=True):
            embed = discord.Embed(description=truncate(message.content or "(sin texto)", 300), color=Colors.DEFAULT)
            embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
            embed.add_field(name="Enviado", value=discord.utils.format_dt(message.created_at, "R"))
            embed.add_field(name="Ir al mensaje", value=f"[abrir]({message.jump_url})")
            return await ctx.send(embed=embed)
        raise BotError("Ese canal no tiene mensajes.")

    # ------------------------------------------------------------------
    # Colores y texto
    # ------------------------------------------------------------------
    @commands.command(name="color", aliases=["colour"], usage="<color>")
    async def color(self, ctx: Context, *, value: str):
        """Muestra un color (hex, `rgb(...)`) con sus valores RGB y HSV."""
        await ctx.send(embed=color_embed(parse_color(value)))

    @commands.command(name="randomcolor", aliases=["rcolor"])
    async def randomcolor(self, ctx: Context):
        """Genera un color al azar."""
        await ctx.send(embed=color_embed(discord.Color(random.randint(0, 0xFFFFFF))))

    @commands.command(name="charinfo", aliases=["unicode"], usage="<texto>")
    async def charinfo(self, ctx: Context, *, text: str):
        """Nombre y código Unicode de cada carácter (máx. 20)."""
        lines: List[str] = []
        for char in text[:20]:
            name = unicodedata.name(char, "desconocido")
            lines.append(f"`U+{ord(char):04X}` {char} — {name.title()}")
        await ctx.neutral("\n".join(lines), title="Caracteres")


async def setup(bot) -> None:
    await bot.add_cog(UtilityInfo(bot))
