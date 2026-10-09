"""Servidor · alias: cada servidor puede crear sus propios atajos para cualquier comando.

    ,alias add un unban      ->  ahora ",un 123" ejecuta ",unban 123"
    ,alias add s snipe       ->  alias de una letra
Los alias reales (nombres de comando y alias integrados) nunca se pueden pisar.
"""
from __future__ import annotations

from typing import Optional

from discord.ext import commands

from core.cog import BaseCog
from core.context import Context
from core.errors import BotError
from core.utils import truncate
from core.views import confirm, paginate_list

MAX_ALIASES = 50


class AliasCog(BaseCog):
    """Alias de comandos por servidor."""

    category = "Servidor"

    def _table(self, guild_id: int) -> dict:
        return self.bot.aliases.setdefault(guild_id, {})

    @commands.group(name="alias", aliases=["aliases"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def alias(self, ctx: Context):
        """Administra los alias de comandos de este servidor."""
        await self.bot.get_cog("Help").show(ctx, ctx.command)

    @alias.command(name="add", aliases=["create"], usage="<alias> <comando>")
    async def alias_add(self, ctx: Context, name: str, *, command: str):
        """Crea un alias para un comando (también sirve para subcomandos, ej. `role add`)."""
        name = name.lower().strip()
        if not 1 <= len(name) <= 32:
            raise BotError("El alias debe tener entre **1** y **32** caracteres, sin espacios.")
        if self.bot.get_command(name) is not None:
            raise BotError(f"No se puede usar **{name}** — ya es el nombre de un comando.")
        table = self._table(ctx.guild.id)
        if name in table:
            raise BotError(f"El alias **{name}** ya existe y apunta a **{table[name]}**.")
        target = self.bot.get_command(command.lower().strip())
        if target is None:
            raise BotError(f"No existe ningún comando llamado `{truncate(command, 40)}`.")
        if len(table) >= MAX_ALIASES:
            raise BotError(f"Este servidor ya tiene **{MAX_ALIASES}** alias.")
        await self.bot.db.execute(
            "INSERT INTO aliases (guild_id, alias, command) VALUES (?, ?, ?)",
            ctx.guild.id, name, target.qualified_name,
        )
        table[name] = target.qualified_name
        await ctx.approve(f"Se añadió el alias **{name}** para **{target.qualified_name}**.")

    @alias.command(name="remove", aliases=["delete", "del"], usage="<alias>")
    async def alias_remove(self, ctx: Context, name: str, *, command: Optional[str] = None):
        """Elimina un alias."""
        name = name.lower().strip()
        table = self._table(ctx.guild.id)
        if name not in table:
            raise BotError(f"No se encontró el alias **{name}**.")
        await self.bot.db.execute("DELETE FROM aliases WHERE guild_id = ? AND alias = ?", ctx.guild.id, name)
        del table[name]
        await ctx.approve(f"Se eliminó el alias **{name}**.")

    @alias.command(name="list", aliases=["all"])
    async def alias_list(self, ctx: Context):
        """Muestra los alias de este servidor."""
        table = self._table(ctx.guild.id)
        if not table:
            raise BotError("Este servidor no tiene alias.")
        lines = [f"`{alias}` → **{command}**" for alias, command in sorted(table.items())]
        icon = ctx.guild.icon.with_size(256).url if ctx.guild.icon else None
        await paginate_list(
            ctx,
            title=f"Alias de {ctx.guild.name}",
            lines=lines,
            subtitle=[f"**{len(lines)}** alias"],
            thumbnail=icon,
        )

    @alias.command(name="removeall", usage="<comando>")
    async def alias_removeall(self, ctx: Context, *, command: str):
        """Elimina todos los alias que apuntan a un comando."""
        target = self.bot.get_command(command.lower().strip())
        name = target.qualified_name if target else command.lower().strip()
        table = self._table(ctx.guild.id)
        doomed = [alias for alias, cmd in table.items() if cmd == name]
        if not doomed:
            raise BotError(f"**{truncate(name, 40)}** no tiene alias en este servidor.")
        await self.bot.db.execute("DELETE FROM aliases WHERE guild_id = ? AND command = ?", ctx.guild.id, name)
        for alias in doomed:
            del table[alias]
        await ctx.approve(f"Se eliminaron **{len(doomed)}** alias de **{name}**.")

    @alias.command(name="reset", aliases=["clear"])
    async def alias_reset(self, ctx: Context):
        """Elimina todos los alias del servidor (pide confirmación)."""
        table = self._table(ctx.guild.id)
        if not table:
            raise BotError("Este servidor no tiene alias.")
        if not await confirm(ctx, f"¿Eliminar los **{len(table)}** alias de este servidor?"):
            return await ctx.warn("Cancelado.")
        amount = len(table)
        await self.bot.db.execute("DELETE FROM aliases WHERE guild_id = ?", ctx.guild.id)
        table.clear()
        await ctx.approve(f"Se eliminaron **{amount}** alias.")


async def setup(bot) -> None:
    await bot.add_cog(AliasCog(bot))
