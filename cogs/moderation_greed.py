"""Comandos adicionales de moderación compatibles con Greed.
Las configuraciones se guardan en settings (SQLite) y sobreviven reinicios.
"""
from __future__ import annotations

import re
from typing import Optional

import discord
from discord.ext import commands

from core import checks
from core.cog import BaseCog
from core.context import Context
from core.errors import BotError

DANGEROUS_PERMISSIONS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members", "moderate_members",
    "mention_everyone", "manage_messages",
)
POLICY_COMMANDS = {"disable", "enable", "restrict", "protect", "denyperm"}
MODERATION_TARGET_COMMANDS = {
    "ban", "unban", "kick", "softban", "tempban", "massban", "unbanall",
    "mute", "unmute", "warn", "delwarn", "clearwarns", "jail", "unjail",
    "nick", "strip", "staffstrip", "hardban", "imute", "iunmute", "rmute",
    "runmute", "strike",
}


class GreedModeration(BaseCog):
    """Comandos extra de moderación y controles persistentes."""

    category = "Moderación"

    async def cog_load(self) -> None:
        self.bot.add_check(self._global_policy)

    async def cog_unload(self) -> None:
        self.bot.remove_check(self._global_policy)

    async def _get_list(self, guild_id: int, key: str) -> list:
        value = await self.bot.db.get_setting(guild_id, key, [])
        return value if isinstance(value, list) else []

    async def _set_list(self, guild_id: int, key: str, value: list) -> None:
        await self.bot.db.set_setting(guild_id, key, value)

    @staticmethod
    def _command_names(ctx: Context) -> set[str]:
        if ctx.command is None:
            return set()
        qualified = ctx.command.qualified_name.casefold()
        return {qualified, qualified.split()[0], ctx.command.name.casefold()}

    async def _global_policy(self, ctx: Context) -> bool:
        """Aplica disable/restrict y protege objetivos antes de ejecutar comandos."""
        if ctx.guild is None or ctx.command is None:
            return True

        names = self._command_names(ctx)
        root = ctx.command.qualified_name.casefold().split()[0]

        # No permitas que una regla bloquee las herramientas para corregirla.
        if root not in POLICY_COMMANDS:
            disabled = await self._get_list(ctx.guild.id, "greed_disabled")
            member_role_ids = {role.id for role in getattr(ctx.author, "roles", [])}
            whitelist = await self._get_list(ctx.guild.id, "greed_disable_whitelist")
            whitelisted = any(
                item.get("command") in names and int(item.get("user_id", 0)) == ctx.author.id
                for item in whitelist if isinstance(item, dict)
            )
            if not whitelisted:
                for item in disabled:
                    if not isinstance(item, dict) or item.get("command") not in names:
                        continue
                    scope = item.get("scope", "guild")
                    target_id = int(item.get("target_id", 0))
                    if scope == "guild" or (scope == "channel" and ctx.channel.id == target_id) or (
                        scope == "role" and target_id in member_role_ids
                    ):
                        raise BotError(f"El comando `{ctx.command.qualified_name}` está deshabilitado aquí.")

            rules = await self._get_list(ctx.guild.id, "greed_restrict")
            for rule in rules:
                if not isinstance(rule, dict) or rule.get("command") not in names:
                    continue
                allow = {int(x) for x in rule.get("allow", [])}
                deny = {int(x) for x in rule.get("deny", [])}
                if deny & member_role_ids:
                    raise BotError("Uno de tus roles tiene prohibido usar este comando.")
                if allow and not (allow & member_role_ids):
                    raise BotError("Este comando está restringido a roles autorizados.")

        if root in MODERATION_TARGET_COMMANDS:
            protected = await self._get_list(ctx.guild.id, "greed_protected")
            protected_members = {
                int(item["id"]) for item in protected
                if isinstance(item, dict) and item.get("type") == "member"
            }
            protected_roles = {
                int(item["id"]) for item in protected
                if isinstance(item, dict) and item.get("type") == "role"
            }

            # Los objetivos mencionados o escritos como ID no se pueden moderar.
            mentioned_member_ids = {m.id for m in ctx.message.mentions}
            mentioned_member_ids.update(
                int(x) for x in re.findall(r"(?<!\d)(\d{15,22})(?!\d)", ctx.message.content)
            )
            if mentioned_member_ids & protected_members:
                raise BotError("Ese usuario está protegido y no puede ser moderado por estos comandos.")

            for member in ctx.message.mentions:
                if any(role.id in protected_roles for role in member.roles):
                    raise BotError(f"{member.mention} tiene un rol protegido y no puede ser moderado.")
            if root == "role" and any(role.id in protected_roles for role in ctx.message.role_mentions):
                raise BotError("Ese rol está protegido.")

        if root == "role" and "add" in names:
            denied = {str(x).casefold() for x in await self._get_list(ctx.guild.id, "greed_denied_permissions")}
            for role in ctx.message.role_mentions:
                blocked = [name for name in denied if getattr(role.permissions, name, False)]
                if blocked:
                    raise BotError(
                        f"No se puede asignar {role.mention}: contiene permisos bloqueados "
                        f"({', '.join(blocked)})."
                    )
        return True

    # ------------------------------------------------------------------
    # Roles especializados: imute / rmute
    # ------------------------------------------------------------------
    async def _restriction_role(self, guild: discord.Guild, kind: str) -> discord.Role:
        setting = f"greed_{kind}_role"
        role_id = await self.bot.db.get_setting(guild.id, setting)
        role = guild.get_role(int(role_id)) if role_id else None
        if role is None:
            role = discord.utils.get(guild.roles, name=kind)
            if role is None:
                role = await guild.create_role(name=kind, reason=f"Configuración de moderación: {kind}")
            await self.bot.db.set_setting(guild.id, setting, role.id)

        for channel in guild.channels:
            overwrite = channel.overwrites_for(role)
            if kind == "imute":
                overwrite.attach_files = False
                overwrite.embed_links = False
                overwrite.use_external_stickers = False
            else:
                overwrite.add_reactions = False
                overwrite.use_external_emojis = False
                overwrite.use_external_stickers = False
            await channel.set_permissions(role, overwrite=overwrite, reason=f"Aplicar rol {kind}")
        return role

    async def _set_restriction(self, ctx: Context, member: discord.Member, kind: str, enabled: bool, reason: Optional[str]):
        checks.ensure_hierarchy(ctx, member, "moderar")
        role = await self._restriction_role(ctx.guild, kind)
        if role >= ctx.guild.me.top_role:
            raise BotError(f"Mi rol debe estar por encima de {role.mention}.")
        if enabled and role in member.roles:
            raise BotError(f"{member.mention} ya tiene la restricción {kind}.")
        if not enabled and role not in member.roles:
            raise BotError(f"{member.mention} no tiene la restricción {kind}.")
        audit = f"{kind} por {ctx.author} — {reason or 'Sin razón'}"
        if enabled:
            await member.add_roles(role, reason=audit)
            await ctx.send(f"Se aplicó **{kind}** a {member.mention}.")
        else:
            await member.remove_roles(role, reason=audit)
            await ctx.send(f"Se retiró **{kind}** a {member.mention}.")

    @commands.command(name="imute", usage="<miembro> [razón]")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def imute(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Impide adjuntar archivos, insertar enlaces y usar stickers externos."""
        await self._set_restriction(ctx, member, "imute", True, reason)

    @commands.command(name="iunmute", usage="<miembro> [razón]")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def iunmute(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Retira la restricción de imágenes y adjuntos."""
        await self._set_restriction(ctx, member, "imute", False, reason)

    @commands.command(name="rmute", usage="<miembro> [razón]")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rmute(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Impide añadir reacciones y usar emojis/stickers externos."""
        await self._set_restriction(ctx, member, "rmute", True, reason)

    @commands.command(name="runmute", usage="<miembro> [razón]")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def runmute(self, ctx: Context, member: discord.Member, *, reason: Optional[str] = None):
        """Retira la restricción de reacciones."""
        await self._set_restriction(ctx, member, "rmute", False, reason)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Mantiene los overwrites si se crea un canal después de configurar los roles."""
        guild = channel.guild
        for kind in ("imute", "rmute"):
            role_id = await self.bot.db.get_setting(guild.id, f"greed_{kind}_role")
            role = guild.get_role(int(role_id)) if role_id else None
            if role is None:
                continue
            overwrite = channel.overwrites_for(role)
            if kind == "imute":
                overwrite.attach_files = False
                overwrite.embed_links = False
                overwrite.use_external_stickers = False
            else:
                overwrite.add_reactions = False
                overwrite.use_external_emojis = False
                overwrite.use_external_stickers = False
            try:
                await channel.set_permissions(role, overwrite=overwrite, reason=f"Aplicar rol {kind}")
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------
    # Protección de miembros y roles
    # ------------------------------------------------------------------
    @commands.group(name="protect", invoke_without_command=True, usage="<miembro|rol>")
    @commands.has_permissions(administrator=True)
    async def protect(self, ctx: Context, target: Optional[str] = None):
        """Activa o quita la protección de un miembro o rol."""
        if target is None:
            return await ctx.send("Uso: `protect <miembro|rol>` o `protect list`.")
        protected = await self._get_list(ctx.guild.id, "greed_protected")
        member = ctx.message.mentions[0] if ctx.message.mentions else None
        role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        item = None
        label = None
        if member is not None:
            item, label = {"type": "member", "id": member.id}, member.mention
        elif role is not None:
            item, label = {"type": "role", "id": role.id}, role.mention
        elif target.isdigit():
            object_id = int(target)
            member_obj = ctx.guild.get_member(object_id)
            role_obj = ctx.guild.get_role(object_id)
            if member_obj:
                item, label = {"type": "member", "id": member_obj.id}, member_obj.mention
            elif role_obj:
                item, label = {"type": "role", "id": role_obj.id}, role_obj.mention
        if item is None:
            raise BotError("Menciona un miembro o rol válido.")
        existing = next((x for x in protected if x == item), None)
        if existing:
            protected.remove(existing)
            await ctx.send(f"Protección retirada de {label}.")
        else:
            protected.append(item)
            await ctx.send(f"{label} ahora está protegido contra los comandos de moderación.")
        await self._set_list(ctx.guild.id, "greed_protected", protected)

    @protect.command(name="list", aliases=["ls"])
    @commands.has_permissions(administrator=True)
    async def protect_list(self, ctx: Context):
        protected = await self._get_list(ctx.guild.id, "greed_protected")
        if not protected:
            return await ctx.send("No hay miembros ni roles protegidos.")
        lines = []
        for item in protected:
            obj = ctx.guild.get_member(int(item["id"])) if item.get("type") == "member" else ctx.guild.get_role(int(item["id"]))
            label = obj.mention if obj else f"`{item['id']}` (no encontrado)"
            lines.append(f"{item['type']}: {label}")
        await ctx.send("**Protegidos:**\n" + "\n".join(lines)[:1800])

    # ------------------------------------------------------------------
    # Permisos de rol bloqueados
    # ------------------------------------------------------------------
    @commands.group(name="denyperm", aliases=["dp"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def denyperm(self, ctx: Context):
        """Bloquea permisos para impedir que se entreguen mediante comandos de rol."""
        denied = await self._get_list(ctx.guild.id, "greed_denied_permissions")
        await ctx.send("**Permisos bloqueados:** " + (", ".join(denied) if denied else "ninguno"))

    @denyperm.command(name="add")
    @commands.has_permissions(administrator=True)
    async def denyperm_add(self, ctx: Context, *, permission: str):
        key = permission.casefold().strip().replace(" ", "_").replace("-", "_")
        if key not in discord.Permissions.VALID_FLAGS:
            raise BotError("Permiso desconocido. Usa `denyperm available` para ver los nombres válidos.")
        denied = await self._get_list(ctx.guild.id, "greed_denied_permissions")
        if key not in denied:
            denied.append(key)
            await self._set_list(ctx.guild.id, "greed_denied_permissions", denied)
        await ctx.send(f"Permiso bloqueado: `{key}`.")

    @denyperm.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def denyperm_remove(self, ctx: Context, *, permission: str):
        key = permission.casefold().strip().replace(" ", "_").replace("-", "_")
        denied = await self._get_list(ctx.guild.id, "greed_denied_permissions")
        if key not in denied:
            raise BotError("Ese permiso no está bloqueado.")
        denied.remove(key)
        await self._set_list(ctx.guild.id, "greed_denied_permissions", denied)
        await ctx.send(f"Permiso desbloqueado: `{key}`.")

    @denyperm.command(name="available", aliases=["list"])
    @commands.has_permissions(administrator=True)
    async def denyperm_available(self, ctx: Context):
        names = sorted(discord.Permissions.VALID_FLAGS)
        await ctx.send("**Permisos disponibles:**\n" + ", ".join(f"`{n}`" for n in names)[:1800])

    @denyperm.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def denyperm_clear(self, ctx: Context):
        await self._set_list(ctx.guild.id, "greed_denied_permissions", [])
        await ctx.send("Se desbloquearon todos los permisos.")

    # ------------------------------------------------------------------
    # Disable / enable: servidor, canal y rol
    # ------------------------------------------------------------------
    async def _add_disabled(self, guild_id: int, command: str, scope: str, target_id: int = 0):
        command = command.casefold().strip()
        if not command:
            raise BotError("Indica el comando que quieres deshabilitar.")
        disabled = await self._get_list(guild_id, "greed_disabled")
        item = {"command": command, "scope": scope, "target_id": int(target_id)}
        if item not in disabled:
            disabled.append(item)
            await self._set_list(guild_id, "greed_disabled", disabled)

    @commands.group(name="disable", invoke_without_command=True, usage="<comando>")
    @commands.has_permissions(administrator=True)
    async def disable(self, ctx: Context, *, command: str):
        """Deshabilita un comando en todo el servidor."""
        await self._add_disabled(ctx.guild.id, command.split()[0], "guild")
        await ctx.send(f"Se deshabilitó `{command.split()[0]}` en todo el servidor.")

    @disable.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def disable_channel(self, ctx: Context, command: str, channel: Optional[discord.TextChannel] = None):
        channel = channel or ctx.channel
        await self._add_disabled(ctx.guild.id, command, "channel", channel.id)
        await ctx.send(f"`{command}` deshabilitado en {channel.mention}.")

    @disable.command(name="role")
    @commands.has_permissions(administrator=True)
    async def disable_role(self, ctx: Context, command: str, *, role: discord.Role):
        await self._add_disabled(ctx.guild.id, command, "role", role.id)
        await ctx.send(f"`{command}` deshabilitado para miembros con {role.mention}.")

    @disable.command(name="list", aliases=["show", "all"])
    @commands.has_permissions(administrator=True)
    async def disable_list(self, ctx: Context):
        disabled = await self._get_list(ctx.guild.id, "greed_disabled")
        if not disabled:
            return await ctx.send("No hay comandos deshabilitados.")
        lines = [f"`{x['command']}` — {x['scope']} ({x.get('target_id', 0)})" for x in disabled]
        await ctx.send("**Comandos deshabilitados:**\n" + "\n".join(lines)[:1800])

    @disable.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def disable_reset(self, ctx: Context, *, command: Optional[str] = None):
        disabled = await self._get_list(ctx.guild.id, "greed_disabled")
        if command:
            disabled = [x for x in disabled if x.get("command") != command.casefold()]
        else:
            disabled = []
        await self._set_list(ctx.guild.id, "greed_disabled", disabled)
        await ctx.send("Se actualizaron las restricciones de comandos.")

    @disable.group(name="whitelist", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def disable_whitelist(self, ctx: Context):
        await ctx.send("Uso: `disable whitelist add <comando> <miembro>`, `list <comando>`, `remove <comando> <miembro>`.")

    @disable_whitelist.command(name="add")
    @commands.has_permissions(administrator=True)
    async def whitelist_add(self, ctx: Context, command: str, member: discord.Member):
        values = await self._get_list(ctx.guild.id, "greed_disable_whitelist")
        item = {"command": command.casefold(), "user_id": member.id}
        if item not in values:
            values.append(item)
        await self._set_list(ctx.guild.id, "greed_disable_whitelist", values)
        await ctx.send(f"{member.mention} puede usar `{command}` aunque esté deshabilitado.")

    @disable_whitelist.command(name="list")
    @commands.has_permissions(administrator=True)
    async def whitelist_list(self, ctx: Context, *, command: str):
        values = await self._get_list(ctx.guild.id, "greed_disable_whitelist")
        lines = [f"<@{x['user_id']}>" for x in values if x.get("command") == command.casefold()]
        await ctx.send("Lista blanca: " + (", ".join(lines) if lines else "vacía"))

    @disable_whitelist.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def whitelist_remove(self, ctx: Context, command: str, member: discord.Member):
        values = await self._get_list(ctx.guild.id, "greed_disable_whitelist")
        values = [x for x in values if not (x.get("command") == command.casefold() and int(x.get("user_id", 0)) == member.id)]
        await self._set_list(ctx.guild.id, "greed_disable_whitelist", values)
        await ctx.send(f"Se quitó a {member.mention} de la lista blanca de `{command}`.")

    @commands.command(name="enable", usage="<comando> [canal|rol]")
    @commands.has_permissions(administrator=True)
    async def enable(self, ctx: Context, command: str, target: Optional[str] = None):
        """Vuelve a habilitar un comando globalmente o en un canal/rol."""
        disabled = await self._get_list(ctx.guild.id, "greed_disabled")
        target_id = None
        if target:
            match = re.search(r"(\d{15,22})", target)
            if match:
                target_id = int(match.group(1))
        if target_id is None:
            disabled = [x for x in disabled if x.get("command") != command.casefold()]
        else:
            disabled = [
                x for x in disabled
                if not (x.get("command") == command.casefold() and int(x.get("target_id", 0)) == target_id)
            ]
        await self._set_list(ctx.guild.id, "greed_disabled", disabled)
        await ctx.send(f"Se habilitó `{command}` para el alcance indicado.")

    # ------------------------------------------------------------------
    # Restrict: allow/deny roles for commands
    # ------------------------------------------------------------------
    @commands.group(name="restrict", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def restrict(self, ctx: Context):
        rules = await self._get_list(ctx.guild.id, "greed_restrict")
        if not rules:
            return await ctx.send("No hay restricciones por rol.")
        lines = []
        for rule in rules:
            allow = ", ".join(f"<@&{x}>" for x in rule.get("allow", [])) or "ninguno"
            deny = ", ".join(f"<@&{x}>" for x in rule.get("deny", [])) or "ninguno"
            lines.append(f"`{rule['command']}`: permitir [{allow}] · denegar [{deny}]")
        await ctx.send("\n".join(lines)[:1800])

    async def _edit_restriction(self, guild_id: int, command: str, role_id: int, mode: str):
        rules = await self._get_list(guild_id, "greed_restrict")
        rule = next((x for x in rules if x.get("command") == command.casefold()), None)
        if rule is None:
            rule = {"command": command.casefold(), "allow": [], "deny": []}
            rules.append(rule)
        opposite = "deny" if mode == "allow" else "allow"
        rule[opposite] = [int(x) for x in rule.get(opposite, []) if int(x) != role_id]
        if role_id not in [int(x) for x in rule.get(mode, [])]:
            rule[mode].append(role_id)
        await self._set_list(guild_id, "greed_restrict", rules)

    @restrict.command(name="allow")
    @commands.has_permissions(administrator=True)
    async def restrict_allow(self, ctx: Context, command: str, *, role: discord.Role):
        await self._edit_restriction(ctx.guild.id, command, role.id, "allow")
        await ctx.send(f"Solo roles autorizados podrán usar `{command}`; añadido {role.mention}.")

    @restrict.command(name="deny", aliases=["add"])
    @commands.has_permissions(administrator=True)
    async def restrict_deny(self, ctx: Context, command: str, *, role: discord.Role):
        await self._edit_restriction(ctx.guild.id, command, role.id, "deny")
        await ctx.send(f"{role.mention} no podrá usar `{command}`.")

    @restrict.command(name="remove", aliases=["delete", "del"])
    @commands.has_permissions(administrator=True)
    async def restrict_remove(self, ctx: Context, command: str, role: discord.Role):
        rules = await self._get_list(ctx.guild.id, "greed_restrict")
        for rule in rules:
            if rule.get("command") == command.casefold():
                rule["allow"] = [int(x) for x in rule.get("allow", []) if int(x) != role.id]
                rule["deny"] = [int(x) for x in rule.get("deny", []) if int(x) != role.id]
        rules = [x for x in rules if x.get("allow") or x.get("deny")]
        await self._set_list(ctx.guild.id, "greed_restrict", rules)
        await ctx.send(f"Se retiró la restricción de {role.mention} para `{command}`.")

    @restrict.command(name="reset", aliases=["clear"])
    @commands.has_permissions(administrator=True)
    async def restrict_reset(self, ctx: Context, command: Optional[str] = None):
        rules = await self._get_list(ctx.guild.id, "greed_restrict")
        if command:
            rules = [x for x in rules if x.get("command") != command.casefold()]
        else:
            rules = []
        await self._set_list(ctx.guild.id, "greed_restrict", rules)
        await ctx.send("Se reiniciaron las restricciones indicadas.")

    # ------------------------------------------------------------------
    # Strike system
    # ------------------------------------------------------------------
    @commands.group(name="strike", invoke_without_command=True, usage="add|remove|clear|list")
    @commands.has_permissions(moderate_members=True)
    async def strike(self, ctx: Context):
        await ctx.send("Uso: `strike add <miembro> [cantidad] [razón]`, `remove <miembro> [cantidad]`, `clear <miembro>`, `list <miembro>`.")

    async def _strikes(self, guild_id: int) -> list:
        return await self._get_list(guild_id, "greed_strikes")

    @strike.command(name="add")
    @commands.has_permissions(moderate_members=True)
    async def strike_add(self, ctx: Context, member: discord.Member, amount: int = 1, *, reason: str = "Sin razón"):
        checks.ensure_hierarchy(ctx, member, "sancionar")
        if amount < 1 or amount > 25:
            raise BotError("La cantidad debe estar entre 1 y 25.")
        values = await self._strikes(ctx.guild.id)
        for _ in range(amount):
            values.append({"user_id": member.id, "moderator_id": ctx.author.id, "reason": reason[:300], "at": discord.utils.utcnow().isoformat()})
        await self._set_list(ctx.guild.id, "greed_strikes", values)
        count = sum(1 for x in values if int(x.get("user_id", 0)) == member.id)
        await ctx.send(f"{member.mention} recibió {amount} strike(s). Total: **{count}**. Razón: {reason}")

    @strike.command(name="remove")
    @commands.has_permissions(moderate_members=True)
    async def strike_remove(self, ctx: Context, member: discord.Member, amount: int = 1):
        values = await self._strikes(ctx.guild.id)
        indices = [i for i, x in enumerate(values) if int(x.get("user_id", 0)) == member.id]
        if not indices:
            raise BotError("Ese miembro no tiene strikes.")
        if amount < 1:
            raise BotError("La cantidad debe ser positiva.")
        remove_indices = set(indices[-amount:])
        values = [x for i, x in enumerate(values) if i not in remove_indices]
        await self._set_list(ctx.guild.id, "greed_strikes", values)
        await ctx.send(f"Se retiraron {len(remove_indices)} strike(s) de {member.mention}.")

    @strike.command(name="clear")
    @commands.has_permissions(moderate_members=True)
    async def strike_clear(self, ctx: Context, member: discord.Member):
        values = await self._strikes(ctx.guild.id)
        remaining = [x for x in values if int(x.get("user_id", 0)) != member.id]
        removed = len(values) - len(remaining)
        await self._set_list(ctx.guild.id, "greed_strikes", remaining)
        await ctx.send(f"Se eliminaron {removed} strike(s) de {member.mention}.")

    @strike.command(name="list")
    @commands.has_permissions(moderate_members=True)
    async def strike_list(self, ctx: Context, member: discord.Member):
        values = [x for x in await self._strikes(ctx.guild.id) if int(x.get("user_id", 0)) == member.id]
        if not values:
            return await ctx.send(f"{member.mention} no tiene strikes.")
        lines = [f"{i}. {x.get('reason', 'Sin razón')} — <@{x.get('moderator_id', 0)}>" for i, x in enumerate(values, 1)]
        await ctx.send(f"**Strikes de {member}: {len(values)}**\n" + "\n".join(lines)[:1700])

    # ------------------------------------------------------------------
    # Staffstrip: quitar roles que conceden permisos peligrosos
    # ------------------------------------------------------------------
    @commands.command(name="staffstrip", usage="<miembro> [razón]")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def staffstrip(self, ctx: Context, member: discord.Member, *, reason: str = "Staffstrip"):
        checks.ensure_hierarchy(ctx, member, "retirar permisos")
        removable = [
            role for role in member.roles
            if not role.is_default()
            and not role.managed
            and role < ctx.guild.me.top_role
            and any(getattr(role.permissions, name, False) for name in DANGEROUS_PERMISSIONS)
        ]
        if not removable:
            raise BotError(f"{member.mention} no tiene roles con permisos peligrosos que pueda retirar.")
        await member.remove_roles(*removable, reason=f"Staffstrip por {ctx.author}: {reason}")
        names = ", ".join(role.name for role in removable)
        await ctx.send(f"Se retiraron estos roles de {member.mention}: {names}.")

async def setup(bot) -> None:
    await bot.add_cog(GreedModeration(bot))
