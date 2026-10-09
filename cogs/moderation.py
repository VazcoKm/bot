"""Moderación: sanciones, warns, jail, casos, modlog y herramientas de apodos."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import time
import unicodedata
from typing import Optional

import discord
from discord.ext import commands, tasks

from core import cases, checks
from core.cog import BaseCog
from core.context import Context
from core.converters import Duration
from core.errors import BotError
from core.utils import format_timedelta, truncate
from core.views import confirm, make_pages, paginate

MAX_TIMEOUT = dt.timedelta(days=28)  # límite de Discord para timeouts
HOIST_CHARS = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "
DANGEROUS_PERMS = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "ban_members",
    "kick_members",
    "moderate_members",
    "mention_everyone",
    "manage_messages",
)


def _why(reason: Optional[str]) -> str:
    return f" — {truncate(reason, 120)}" if reason else ""


class Moderation(BaseCog):
    """Sanciones y casos."""

    category = "Moderación"

    async def cog_load(self) -> None:
        self.check_timed_actions.start()

    async def cog_unload(self) -> None:
        self.check_timed_actions.cancel()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _is_banned(self, guild: discord.Guild, user: discord.abc.Snowflake) -> bool:
        try:
            await guild.fetch_ban(discord.Object(id=user.id))
            return True
        except discord.NotFound:
            return False

    async def _add_timed(self, guild_id: int, user_id: int, action: str, expires_at: float) -> None:
        await self._del_timed(guild_id, user_id, action)
        await self.bot.db.execute(
            "INSERT INTO timed_actions (guild_id, user_id, action, expires_at) VALUES (?, ?, ?, ?)",
            guild_id,
            user_id,
            action,
            expires_at,
        )

    async def _del_timed(self, guild_id: int, user_id: int, action: str) -> None:
        await self.bot.db.execute(
            "DELETE FROM timed_actions WHERE guild_id = ? AND user_id = ? AND action = ?",
            guild_id,
            user_id,
            action,
        )

    async def _jail_role(self, guild: discord.Guild, prefix: str = ";") -> discord.Role:
        role_id = await self.bot.db.get_setting(guild.id, "jail_role")
        role = guild.get_role(role_id) if role_id else None
        if role is None:
            raise BotError(f"La cárcel no está configurada. Un admin debe usar `{prefix}jail setup`.")
        if role >= guild.me.top_role:
            raise BotError(f"Mi rol debe estar por encima de {role.mention} para poder usar la cárcel.")
        return role

    async def _release(self, guild: discord.Guild, member: discord.Member, reason: str) -> None:
        """Quita el rol de cárcel y devuelve los roles que tenía."""
        role = await self._jail_role(guild)
        row = await self.bot.db.fetchone(
            "SELECT role_ids FROM jail_roles WHERE guild_id = ? AND user_id = ?", guild.id, member.id
        )
        saved = json.loads(row["role_ids"]) if row else []
        restore = []
        for role_id in saved:
            saved_role = guild.get_role(role_id)
            if saved_role and not saved_role.managed and saved_role < guild.me.top_role:
                restore.append(saved_role)
        current = [r for r in member.roles if not r.is_default() and r.id != role.id]
        new_roles = list(dict.fromkeys(current + restore))
        await member.edit(roles=new_roles, reason=reason)
        await self.bot.db.execute(
            "DELETE FROM jail_roles WHERE guild_id = ? AND user_id = ?", guild.id, member.id
        )
        await self._del_timed(guild.id, member.id, "unjail")

    # ------------------------------------------------------------------
    # Tareas en segundo plano y listeners
    # ------------------------------------------------------------------
    @tasks.loop(seconds=30)
    async def check_timed_actions(self) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM timed_actions WHERE expires_at <= ?", time.time()
        )
        for row in rows:
            await self.bot.db.execute("DELETE FROM timed_actions WHERE id = ?", row["id"])
            guild = self.bot.get_guild(row["guild_id"])
            if guild is None:
                continue
            try:
                if row["action"] == "unban":
                    await guild.unban(discord.Object(id=row["user_id"]), reason="Tempban expirado")
                    await cases.log(
                        self.bot, guild, discord.Object(id=row["user_id"]), guild.me, "unban", "Tempban expirado"
                    )
                elif row["action"] == "unjail":
                    member = guild.get_member(row["user_id"])
                    if member is not None:
                        await self._release(guild, member, "Jail expirado")
                        await cases.log(self.bot, guild, member, guild.me, "unjail", "Jail expirado")
            except (discord.HTTPException, BotError):
                pass

    @check_timed_actions.before_loop
    async def _before_timed(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Si alguien se sale estando en la cárcel y vuelve, lo encarcelamos otra vez."""
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM jail_roles WHERE guild_id = ? AND user_id = ?", member.guild.id, member.id
        )
        if row is None:
            return
        try:
            role = await self._jail_role(member.guild)
            await member.add_roles(role, reason="Volvió al servidor estando en la cárcel")
        except (discord.HTTPException, BotError):
            pass

    # ------------------------------------------------------------------
    # Bans
    # ------------------------------------------------------------------
    @commands.command(name="ban", aliases=["b", "hackban"], usage="<usuario> [razón]")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx: Context, user: discord.User, *, reason: Optional[str] = None):
        """Banea a un usuario (también por ID, aunque no esté en el servidor)."""
        member = ctx.guild.get_member(user.id)
        if member is not None:
            checks.ensure_hierarchy(ctx, member, "banear")
        elif user.id == ctx.author.id:
            raise BotError("No puedes banear a ti mismo.")
        if await self._is_banned(ctx.guild, user):
            raise BotError(f"**{user}** ya está baneado.")
        await cases.dm_user(self.bot, ctx.guild, user, "ban", reason)
        await ctx.guild.ban(user, reason=cases.audit_reason(ctx.author, reason), delete_message_seconds=0)
        case_id = await cases.log(self.bot, ctx.guild, user, ctx.author, "ban", reason)
        await ctx.approve(f"**{user}** fue baneado · caso `#{case_id}`{_why(reason)}")

    @commands.command(name="unban", aliases=["ub"], usage="<usuario> [razón]")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx: Context, user: discord.User, *, reason: Optional[str] = None):
        """Quita el ban a un usuario (por mención o ID)."""
        if not await self._is_banned(ctx.guild, user):
            raise BotError(f"No se pudo desbanear a **{user}** — no está baneado.", kind="error")
        await ctx.guild.unban(user, reason=cases.audit_reason(ctx.author, reason))
        await self._del_timed(ctx.guild.id, user.id, "unban")
        case_id = await cases.log(self.bot, ctx.guild, user, ctx.author, "unban", reason)
        await ctx.approve(f"**{user}** fue desbaneado · caso `#{case_id}`{_why(reason)}")

    @commands.command(name="kick", aliases=["k"], usage="<miembro> [razón]")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Expulsa a un miembro del servidor."""
        checks.ensure_hierarchy(ctx, member, "expulsar")
        await cases.dm_user(self.bot, ctx.guild, member, "kick", reason)
        await member.kick(reason=cases.audit_reason(ctx.author, reason))
        case_id = await cases.log(self.bot, ctx.guild, member, ctx.author, "kick", reason)
        await ctx.approve(f"**{member}** fue expulsado · caso `#{case_id}`{_why(reason)}")

    @commands.command(name="softban", aliases=["sb"], usage="<miembro> [razón]")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Banea y desbanea al instante para borrar sus mensajes de los últimos 7 días."""
        checks.ensure_hierarchy(ctx, member, "banear")
        await cases.dm_user(self.bot, ctx.guild, member, "softban", reason)
        audit = cases.audit_reason(ctx.author, f"Softban: {reason or 'Sin razón'}")
        await ctx.guild.ban(member, reason=audit, delete_message_seconds=7 * 86400)
        await ctx.guild.unban(member, reason=audit)
        case_id = await cases.log(self.bot, ctx.guild, member, ctx.author, "softban", reason)
        await ctx.approve(f"**{member}** recibió un softban · caso `#{case_id}`{_why(reason)}")

    @commands.command(name="tempban", aliases=["tb"], usage="<usuario> <duración> [razón]")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def tempban(self, ctx: Context, user: discord.User, duration: Duration, *, reason: Optional[str] = None):
        """Banea temporalmente; el bot lo desbanea solo al cumplirse el tiempo."""
        if duration < dt.timedelta(minutes=1):
            raise BotError("La duración mínima de un tempban es **1 minuto**.")
        member = ctx.guild.get_member(user.id)
        if member is not None:
            checks.ensure_hierarchy(ctx, member, "banear")
        elif user.id == ctx.author.id:
            raise BotError("No puedes banear a ti mismo.")
        if await self._is_banned(ctx.guild, user):
            raise BotError(f"**{user}** ya está baneado.")
        expires = time.time() + duration.total_seconds()
        await cases.dm_user(self.bot, ctx.guild, user, "tempban", reason, duration=duration)
        await ctx.guild.ban(user, reason=cases.audit_reason(ctx.author, reason), delete_message_seconds=0)
        await self._add_timed(ctx.guild.id, user.id, "unban", expires)
        case_id = await cases.log(self.bot, ctx.guild, user, ctx.author, "tempban", reason, expires_at=expires)
        await ctx.approve(
            f"**{user}** fue baneado por **{format_timedelta(duration)}** · caso `#{case_id}`{_why(reason)}"
        )

    @commands.command(name="massban", aliases=["mban"], usage="<usuarios...> [razón]")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def massban(self, ctx: Context, users: commands.Greedy[discord.User], *, reason: Optional[str] = None):
        """Banea a varios usuarios a la vez (menciones o IDs, máximo 30)."""
        if not users:
            raise BotError("Indica al menos un usuario (mención o ID).")
        if len(users) > 30:
            raise BotError("Máximo **30** usuarios por comando.")
        banned, failed = 0, 0
        for user in users:
            member = ctx.guild.get_member(user.id)
            try:
                if member is not None:
                    checks.ensure_hierarchy(ctx, member, "banear")
                elif user.id == ctx.author.id:
                    raise BotError("self")
                await ctx.guild.ban(user, reason=cases.audit_reason(ctx.author, reason), delete_message_seconds=0)
                await cases.log(self.bot, ctx.guild, user, ctx.author, "ban", reason)
                banned += 1
            except (BotError, discord.HTTPException):
                failed += 1
            await asyncio.sleep(0.4)
        extra = f" · **{failed}** no se pudieron banear" if failed else ""
        await ctx.approve(f"**{banned}** usuarios baneados{extra}{_why(reason)}")

    @commands.command(name="bans", aliases=["banlist"])
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def bans(self, ctx: Context):
        """Lista los usuarios baneados del servidor (hasta 1000)."""
        lines = []
        async for entry in ctx.guild.bans(limit=1000):
            lines.append(f"`{entry.user.id}` · **{entry.user}** — {truncate(entry.reason or 'Sin razón', 60)}")
        if not lines:
            return await ctx.warn("No hay usuarios baneados.")
        await paginate(ctx, make_pages(lines, title=f"Baneados ({len(lines)})"))

    @commands.command(name="unbanall")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def unbanall(self, ctx: Context):
        """Desbanea a TODOS los usuarios baneados (pide confirmación)."""
        entries = [entry async for entry in ctx.guild.bans(limit=None)]
        if not entries:
            return await ctx.warn("No hay usuarios baneados.")
        if not await confirm(ctx, f"¿Seguro que quieres desbanear a **{len(entries)}** usuarios?"):
            return await ctx.warn("Cancelado.")
        done = 0
        for entry in entries:
            try:
                await ctx.guild.unban(entry.user, reason=cases.audit_reason(ctx.author, "unbanall"))
                done += 1
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.4)
        await ctx.approve(f"Se desbanearon **{done}** de **{len(entries)}** usuarios.")

    # ------------------------------------------------------------------
    # Mutes (timeout de Discord)
    # ------------------------------------------------------------------
    @commands.command(name="mute", aliases=["timeout", "tm", "m"], usage="<miembro> [duración] [razón]")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def mute(
        self,
        ctx: Context,
        member: discord.Member,
        duration: Optional[Duration] = None,
        *,
        reason: Optional[str] = None,
    ):
        """Silencia (timeout) a un miembro. Sin duración = 28 días, el máximo de Discord."""
        checks.ensure_hierarchy(ctx, member, "silenciar")
        delta = MAX_TIMEOUT if duration is None else duration
        if delta.total_seconds() <= 0:
            raise BotError("La duración debe ser mayor a 0.")
        if delta > MAX_TIMEOUT:
            raise BotError("El máximo de un mute es de **28 días** (límite de Discord).")
        await member.timeout(discord.utils.utcnow() + delta, reason=cases.audit_reason(ctx.author, reason))
        await cases.dm_user(self.bot, ctx.guild, member, "mute", reason, duration=delta)
        expires = time.time() + delta.total_seconds()
        case_id = await cases.log(self.bot, ctx.guild, member, ctx.author, "mute", reason, expires_at=expires)
        await ctx.approve(
            f"**{member}** fue silenciado por **{format_timedelta(delta)}** · caso `#{case_id}`{_why(reason)}"
        )

    @commands.command(name="unmute", aliases=["untimeout", "um"], usage="<miembro> [razón]")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def unmute(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Quita el silencio (timeout) a un miembro."""
        if not member.is_timed_out():
            raise BotError(f"**{member}** no está silenciado.")
        await member.timeout(None, reason=cases.audit_reason(ctx.author, reason))
        case_id = await cases.log(self.bot, ctx.guild, member, ctx.author, "unmute", reason)
        await ctx.approve(f"**{member}** ya no está silenciado · caso `#{case_id}`{_why(reason)}")

    @commands.command(name="muted", aliases=["mutelist"])
    @commands.has_permissions(moderate_members=True)
    async def muted(self, ctx: Context):
        """Lista los miembros silenciados (timeout) en este momento."""
        members = [m for m in ctx.guild.members if m.is_timed_out()]
        if not members:
            return await ctx.warn("No hay miembros silenciados.")
        lines = [f"{m.mention} · termina <t:{int(m.timed_out_until.timestamp())}:R>" for m in members]
        await paginate(ctx, make_pages(lines, title=f"Silenciados ({len(lines)})"))

    # ------------------------------------------------------------------
    # Warns
    # ------------------------------------------------------------------
    @commands.command(name="warn", aliases=["w"], usage="<miembro> [razón]")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Advierte a un miembro y lo guarda como caso."""
        checks.ensure_hierarchy(ctx, member, "advertir")
        case_id = await cases.log(self.bot, ctx.guild, member, ctx.author, "warn", reason)
        await cases.dm_user(self.bot, ctx.guild, member, "warn", reason)
        total = await cases.count_active(self.bot, ctx.guild.id, member.id, "warn")
        await ctx.approve(
            f"**{member}** fue advertido · caso `#{case_id}` · warns activos: **{total}**{_why(reason)}"
        )

    @commands.command(name="warnings", aliases=["warns"], usage="[usuario]")
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx: Context, user: Optional[discord.User] = None):
        """Lista los warns activos de un usuario."""
        user = user or ctx.author
        rows = await cases.user_cases(self.bot, ctx.guild.id, user.id, action="warn", active_only=True)
        if not rows:
            return await ctx.warn(f"**{user}** no tiene warns activos.")
        lines = [cases.case_line(row) for row in rows]
        await paginate(ctx, make_pages(lines, title=f"Warns de {user} ({len(rows)})"))

    @commands.command(name="delwarn", aliases=["unwarn", "rmwarn"], usage="<número de caso>")
    @commands.has_permissions(moderate_members=True)
    async def delwarn(self, ctx: Context, case_id: int):
        """Elimina un warn concreto por su número de caso."""
        row = await cases.get(self.bot, ctx.guild.id, case_id)
        if row is None or row["action"] != "warn":
            raise BotError(f"El caso `#{case_id}` no existe o no es un warn.")
        if not row["active"]:
            raise BotError(f"El warn `#{case_id}` ya estaba eliminado.")
        await cases.deactivate(self.bot, ctx.guild.id, case_id)
        await ctx.approve(f"Warn `#{case_id}` eliminado.")

    @commands.command(name="clearwarns", aliases=["resetwarns"], usage="<usuario>")
    @commands.has_permissions(moderate_members=True)
    async def clearwarns(self, ctx: Context, user: discord.User):
        """Elimina todos los warns activos de un usuario."""
        removed = await cases.clear_active(self.bot, ctx.guild.id, user.id, "warn")
        if not removed:
            raise BotError(f"**{user}** no tiene warns activos.")
        await ctx.approve(f"Se eliminaron **{removed}** warns de **{user}**.")

    # ------------------------------------------------------------------
    # Jail
    # ------------------------------------------------------------------
    @commands.group(name="jail", aliases=["j"], invoke_without_command=True, usage="<miembro> [duración] [razón]")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def jail(
        self,
        ctx: Context,
        member: discord.Member,
        duration: Optional[Duration] = None,
        *,
        reason: Optional[str] = None,
    ):
        """Encarcela a un miembro: le quita sus roles y solo ve el canal de cárcel."""
        checks.ensure_hierarchy(ctx, member, "encarcelar")
        role = await self._jail_role(ctx.guild, ctx.clean_prefix)
        if role in member.roles:
            raise BotError(f"**{member}** ya está en la cárcel.")
        if duration is not None and duration.total_seconds() <= 0:
            raise BotError("La duración debe ser mayor a 0.")

        me_top = ctx.me.top_role
        removable = [r for r in member.roles if not r.is_default() and not r.managed and r < me_top]
        keep = [r for r in member.roles if not r.is_default() and r not in removable]
        await member.edit(roles=keep + [role], reason=cases.audit_reason(ctx.author, reason))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO jail_roles (guild_id, user_id, role_ids) VALUES (?, ?, ?)",
            ctx.guild.id,
            member.id,
            json.dumps([r.id for r in removable]),
        )
        expires = None
        if duration is not None:
            expires = time.time() + duration.total_seconds()
            await self._add_timed(ctx.guild.id, member.id, "unjail", expires)
        await cases.dm_user(self.bot, ctx.guild, member, "jail", reason, duration=duration)
        case_id = await cases.log(self.bot, ctx.guild, member, ctx.author, "jail", reason, expires_at=expires)
        for_text = f" por **{format_timedelta(duration)}**" if duration else ""
        await ctx.approve(f"**{member}** fue encarcelado{for_text} · caso `#{case_id}`{_why(reason)}")

    @jail.command(name="setup", aliases=["config"])
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def jail_setup(self, ctx: Context):
        """Crea el rol y el canal de cárcel y configura los permisos del servidor."""
        guild = ctx.guild
        reason = f"Jail setup por {ctx.author}"
        working = await ctx.warn("Configurando la cárcel… esto puede tardar si el servidor tiene muchos canales.")

        role_id = await self.bot.db.get_setting(guild.id, "jail_role")
        role = guild.get_role(role_id) if role_id else None
        if role is None:
            role = await guild.create_role(name="Jailed", reason=reason)

        channel_id = await self.bot.db.get_setting(guild.id, "jail_channel")
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }
            channel = await guild.create_text_channel("jail", overwrites=overwrites, reason=reason)

        adjusted = 0
        for target in guild.channels:
            if target.id == channel.id or target.permissions_synced:
                continue  # los canales sincronizados heredan de su categoría
            try:
                await target.set_permissions(
                    role,
                    view_channel=False,
                    send_messages=False,
                    add_reactions=False,
                    connect=False,
                    speak=False,
                    reason=reason,
                )
                adjusted += 1
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.3)

        await self.bot.db.set_setting(guild.id, "jail_role", role.id)
        await self.bot.db.set_setting(guild.id, "jail_channel", channel.id)
        try:
            await working.delete()
        except discord.HTTPException:
            pass
        await ctx.approve(
            f"Cárcel lista: {role.mention} y {channel.mention} · permisos ajustados en **{adjusted}** canales/categorías."
        )

    @commands.command(name="unjail", aliases=["free"], usage="<miembro> [razón]")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unjail(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Saca a un miembro de la cárcel y le devuelve sus roles."""
        role = await self._jail_role(ctx.guild, ctx.clean_prefix)
        if role not in member.roles:
            raise BotError(f"**{member}** no está en la cárcel.")
        await self._release(ctx.guild, member, cases.audit_reason(ctx.author, reason))
        case_id = await cases.log(self.bot, ctx.guild, member, ctx.author, "unjail", reason)
        await ctx.approve(f"**{member}** salió de la cárcel · caso `#{case_id}`{_why(reason)}")

    @commands.command(name="jailed", aliases=["jaillist"])
    @commands.has_permissions(moderate_members=True)
    async def jailed(self, ctx: Context):
        """Lista a los miembros que están en la cárcel."""
        rows = await self.bot.db.fetchall("SELECT user_id FROM jail_roles WHERE guild_id = ?", ctx.guild.id)
        if not rows:
            return await ctx.warn("No hay nadie en la cárcel.")
        lines = [f"<@{row['user_id']}> (`{row['user_id']}`)" for row in rows]
        await paginate(ctx, make_pages(lines, title=f"En la cárcel ({len(lines)})"))

    # ------------------------------------------------------------------
    # Casos y modlog
    # ------------------------------------------------------------------
    @commands.command(name="case", usage="<número>")
    @commands.has_permissions(moderate_members=True)
    async def case(self, ctx: Context, number: int):
        """Muestra el detalle de un caso."""
        row = await cases.get(self.bot, ctx.guild.id, number)
        if row is None:
            raise BotError(f"El caso `#{number}` no existe.")
        await ctx.send(embed=cases.case_embed(row))

    @commands.command(name="history", aliases=["cases", "modlogs"], usage="[usuario]")
    @commands.has_permissions(moderate_members=True)
    async def history(self, ctx: Context, user: Optional[discord.User] = None):
        """Historial de casos de un usuario (o los últimos del servidor)."""
        if user is not None:
            rows = await cases.user_cases(self.bot, ctx.guild.id, user.id)
            title = f"Historial de {user}"
        else:
            rows = await cases.recent(self.bot, ctx.guild.id)
            title = "Últimos casos del servidor"
        if not rows:
            return await ctx.warn("No hay casos registrados.")
        lines = [cases.case_line(row, show_user=user is None) for row in rows]
        await paginate(ctx, make_pages(lines, title=title))

    @commands.command(name="reason", usage="<número de caso> <nueva razón>")
    @commands.has_permissions(moderate_members=True)
    async def reason(self, ctx: Context, number: int, *, new_reason: str):
        """Edita la razón de un caso."""
        if await cases.get(self.bot, ctx.guild.id, number) is None:
            raise BotError(f"El caso `#{number}` no existe.")
        await cases.set_reason(self.bot, ctx.guild.id, number, truncate(new_reason, 500))
        await ctx.approve(f"Razón del caso `#{number}` actualizada.")

    @commands.command(name="modstats", usage="[moderador]")
    @commands.has_permissions(moderate_members=True)
    async def modstats(self, ctx: Context, moderator: Optional[discord.User] = None):
        """Cuántas acciones de cada tipo ha hecho un moderador."""
        moderator = moderator or ctx.author
        rows = await self.bot.db.fetchall(
            "SELECT action, COUNT(*) AS n FROM cases WHERE guild_id = ? AND mod_id = ? "
            "GROUP BY action ORDER BY n DESC",
            ctx.guild.id,
            moderator.id,
        )
        if not rows:
            return await ctx.warn(f"**{moderator}** no ha registrado acciones.")
        total = sum(row["n"] for row in rows)
        lines = [f"**{cases.ACTIONS.get(r['action'], (r['action'].title(),))[0]}** · {r['n']}" for r in rows]
        await ctx.neutral("\n".join(lines), title=f"Acciones de {moderator} ({total})")

    @commands.group(name="modlog", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def modlog(self, ctx: Context):
        """Muestra el canal donde se publican los casos de moderación."""
        channel_id = await self.bot.db.get_setting(ctx.guild.id, "modlog_channel")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            return await ctx.warn(f"No hay canal de modlog. Usa `{ctx.clean_prefix}modlog set #canal`.")
        await ctx.neutral(f"Los casos se publican en {channel.mention}.")

    @modlog.command(name="set", aliases=["channel"], usage="<#canal>")
    @commands.has_permissions(manage_guild=True)
    async def modlog_set(self, ctx: Context, channel: discord.TextChannel):
        """Define el canal del modlog."""
        perms = channel.permissions_for(ctx.me)
        if not (perms.send_messages and perms.embed_links):
            raise BotError(f"Necesito permiso para enviar mensajes e insertar enlaces en {channel.mention}.")
        await self.bot.db.set_setting(ctx.guild.id, "modlog_channel", channel.id)
        await ctx.approve(f"Los casos de moderación se publicarán en {channel.mention}.")

    @modlog.command(name="off", aliases=["remove", "disable"])
    @commands.has_permissions(manage_guild=True)
    async def modlog_off(self, ctx: Context):
        """Desactiva el modlog."""
        await self.bot.db.del_setting(ctx.guild.id, "modlog_channel")
        await ctx.approve("Modlog desactivado.")

    # ------------------------------------------------------------------
    # Apodos y roles
    # ------------------------------------------------------------------
    @commands.command(name="nick", aliases=["nickname", "setnick"], usage="<miembro> [apodo]")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nick(self, ctx: Context, member: discord.Member, *, nickname: Optional[str] = None):
        """Cambia el apodo de un miembro. Sin apodo, se lo quita."""
        checks.ensure_hierarchy(ctx, member, "moderar", allow_self=True)
        if nickname and len(nickname) > 32:
            raise BotError("El apodo no puede superar los **32** caracteres.")
        await member.edit(nick=nickname, reason=cases.audit_reason(ctx.author, "Cambio de apodo"))
        if nickname:
            await ctx.approve(f"Apodo de **{member.name}** cambiado a `{nickname}`.")
        else:
            await ctx.approve(f"Apodo de **{member.name}** eliminado.")

    @commands.command(name="dehoist", usage="<miembro>")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def dehoist(self, ctx: Context, member: discord.Member):
        """Quita los símbolos iniciales del nombre que lo suben al tope de la lista."""
        checks.ensure_hierarchy(ctx, member, "moderar", allow_self=True)
        name = member.display_name
        cleaned = name.lstrip(HOIST_CHARS)
        if cleaned == name:
            raise BotError(f"**{member.name}** no tiene símbolos que lo suban en la lista.")
        cleaned = cleaned[:32] or "Sin nombre"
        await member.edit(nick=cleaned, reason=cases.audit_reason(ctx.author, "Dehoist"))
        await ctx.approve(f"Apodo de **{member.name}** limpiado: `{cleaned}`.")

    @commands.command(name="decancer", usage="<miembro>")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def decancer(self, ctx: Context, member: discord.Member):
        """Convierte un nombre con letras raras en texto normal."""
        checks.ensure_hierarchy(ctx, member, "moderar", allow_self=True)
        name = member.display_name
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        ascii_name = re.sub(r"\s+", " ", ascii_name).strip()[:32] or "Nombre moderado"
        if ascii_name == name:
            raise BotError(f"El nombre de **{member.name}** ya es normal.")
        await member.edit(nick=ascii_name, reason=cases.audit_reason(ctx.author, "Decancer"))
        await ctx.approve(f"Apodo de **{member.name}** normalizado: `{ascii_name}`.")

    @commands.command(name="strip", aliases=["stripstaff"], usage="<miembro> [razón]")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def strip(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Quita todos los roles con permisos peligrosos (staff) a un miembro."""
        checks.ensure_hierarchy(ctx, member, "moderar")
        to_remove = [
            r
            for r in member.roles
            if not r.is_default()
            and not r.managed
            and r < ctx.me.top_role
            and any(getattr(r.permissions, perm) for perm in DANGEROUS_PERMS)
        ]
        if not to_remove:
            raise BotError(f"**{member.name}** no tiene roles con permisos peligrosos que yo pueda quitar.")
        await member.remove_roles(*to_remove, reason=cases.audit_reason(ctx.author, reason or "Strip"))
        await ctx.approve(f"Se quitaron **{len(to_remove)}** roles a **{member.name}**{_why(reason)}")

    @commands.command(name="block", aliases=["cban"], usage="<miembro> [#canal] [razón]")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def block(
        self,
        ctx: Context,
        member: discord.Member,
        channel: Optional[discord.TextChannel] = None,
        *,
        reason: Optional[str] = None,
    ):
        """Bloquea a un miembro en un canal (no lo ve ni escribe)."""
        channel = channel or ctx.channel
        checks.ensure_hierarchy(ctx, member, "moderar")
        overwrite = channel.overwrites_for(member)
        overwrite.view_channel = False
        overwrite.send_messages = False
        await channel.set_permissions(member, overwrite=overwrite, reason=cases.audit_reason(ctx.author, reason))
        await ctx.approve(f"**{member.name}** fue bloqueado en {channel.mention}{_why(reason)}")

    @commands.command(name="unblock", aliases=["uncban"], usage="<miembro> [#canal]")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unblock(self, ctx: Context, member: discord.Member, channel: Optional[discord.TextChannel] = None):
        """Quita el bloqueo de un miembro en un canal."""
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(member)
        if overwrite.view_channel is not False:
            raise BotError(f"**{member.name}** no está bloqueado en {channel.mention}.")
        overwrite.view_channel = None
        overwrite.send_messages = None
        await channel.set_permissions(
            member,
            overwrite=None if overwrite.is_empty() else overwrite,
            reason=cases.audit_reason(ctx.author, "Unblock"),
        )
        await ctx.approve(f"**{member.name}** ya puede ver {channel.mention}.")


async def setup(bot) -> None:
    await bot.add_cog(Moderation(bot))
