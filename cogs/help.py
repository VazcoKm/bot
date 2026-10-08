"""Help al estilo Greed.

`help`                -> resumen de categorías
`help <categoría>`    -> lista paginada de comandos
`help <comando>`      -> embed por comando (autor, título, descripción en cita, Aliases /
                         Parameters / Information, bloque Usage) y una página por subcomando,
                         con los botones ◀ ▶ 🔍 🚫.

Los grupos que quieran mostrar su ayuda al usarse sin subcomando pueden llamar:
    await self.bot.get_cog("Help").show(ctx, ctx.command)
"""
from __future__ import annotations

import inspect
from typing import Dict, List, Optional

import discord
from discord.ext import commands

from config import BOT_NAME, Colors
from core.cog import BaseCog
from core.context import Context
from core.emojis import emojis
from core.errors import BotError
from core.utils import param_name, perm_name, strip_accents, truncate
from core.views import make_pages, paginate

CATEGORY_ORDER = ["Moderación", "Utilidad", "Servidor", "Voicemaster", "Setup", "Logs", "Seguridad", "Extras"]

# Valores de ejemplo para generar la línea "Example:" automáticamente.
SAMPLES = {
    "user": "@usuario", "member": "@usuario", "users": "@usuario1 @usuario2", "channel": "#canal",
    "role": "@rol", "amount": "10", "duration": "10m", "reason": "texto", "new_reason": "texto",
    "number": "1", "case_id": "1", "text": "texto", "nickname": "apodo", "source": "#voz1",
    "destination": "#voz2", "query": "texto", "moderator": "@moderador", "name": "nombre",
    "module": "moderation", "emoji": ":emoji:",
}


def _own_required_perms(command: commands.Command) -> List[str]:
    """Permisos que exige el *usuario* (has_permissions) en el comando y en sus padres."""
    found: List[str] = []
    for cmd in [command, *command.parents]:
        for check in cmd.checks:
            if getattr(check, "__qualname__", "").startswith("has_permissions"):
                try:
                    perms = inspect.getclosurevars(check).nonlocals.get("perms", {})
                except (TypeError, ValueError):
                    continue
                for perm, needed in perms.items():
                    if needed and perm not in found:
                        found.append(perm)
    return found


def _visible_subcommands(command: commands.Command) -> List[commands.Command]:
    """Subcomandos en el orden en que se registraron (Group.commands es un set sin orden)."""
    if not isinstance(command, commands.Group):
        return []
    ordered: List[commands.Command] = []
    seen = set()
    for sub in command.all_commands.values():  # incluye alias: deduplicamos
        if id(sub) not in seen and not sub.hidden and sub.enabled:
            seen.add(id(sub))
            ordered.append(sub)
    return ordered


def _walk(command: commands.Command) -> List[commands.Command]:
    """El comando y todos sus subcomandos, en orden de registro."""
    result = [command]
    for sub in _visible_subcommands(command):
        result.extend(_walk(sub))
    return result


def _syntax(prefix: str, command: commands.Command) -> str:
    """',hardban (usuario) [historial] [razón]' o ',alias (add | remove | list)'."""
    parts = [f"{prefix}{command.qualified_name}"]
    params = list(command.clean_params.values())
    for param in params:
        name = param_name(param.name)
        parts.append(f"({name})" if param.required else f"[{name}]")
    text = " ".join(parts)
    subs = _visible_subcommands(command)
    if subs:
        names = " | ".join(c.name for c in subs)
        text = f"{text} ({names})" if not params else f"{text}\nSubcomandos: {names}"
    return text


def _example(prefix: str, command: commands.Command) -> str:
    custom = command.extras.get("example")
    if custom:
        return f"{prefix}{custom}"
    parts = [f"{prefix}{command.qualified_name}"]
    for param in command.clean_params.values():
        parts.append(SAMPLES.get(param.name, param_name(param.name)))
    return " ".join(parts)


class Help(BaseCog):
    guild_only = False

    # ------------------------------------------------------------------
    # Construcción de embeds
    # ------------------------------------------------------------------
    def _categories(self) -> Dict[str, List[commands.Command]]:
        found: Dict[str, List[commands.Command]] = {}
        for cog in self.bot.cogs.values():
            category = getattr(cog, "category", None)
            if not category:
                continue
            for command in cog.walk_commands():
                if command.hidden or not command.enabled:
                    continue
                found.setdefault(category, []).append(command)
        ordered = {name: found[name] for name in CATEGORY_ORDER if name in found}
        for name in sorted(found):
            ordered.setdefault(name, found[name])
        return ordered

    def _overview(self, ctx: Context, categories: Dict[str, List[commands.Command]]) -> discord.Embed:
        prefix = ctx.clean_prefix
        total = sum(len(cmds) for cmds in categories.values())
        embed = discord.Embed(title=f"{BOT_NAME} · Ayuda", color=Colors.DEFAULT)
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        embed.description = (
            f"Prefijo: `{prefix}`\n"
            f"`{prefix}help <categoría>` lista sus comandos · `{prefix}help <comando>` da el detalle.\n"
            f"**{total}** comandos en **{len(categories)}** categorías."
        )
        for name, cmds in categories.items():
            embed.add_field(name=name, value=f"{len(cmds)} comandos", inline=True)
        return embed

    def _command_page(
        self, ctx: Context, command: commands.Command, number: int, total: int
    ) -> discord.Embed:
        prefix = ctx.clean_prefix
        description = (command.help or "Sin descripción.").strip().splitlines()[0]
        embed = discord.Embed(
            title=command.qualified_name,
            description=f"> {description}",
            color=Colors.DEFAULT,
        )
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)

        aliases = ", ".join(f"`{a}`" for a in command.aliases) or "n/a"
        params = ", ".join(param_name(p.name) for p in command.clean_params.values()) or "n/a"
        perms = ", ".join(f"{emojis.warn} {perm_name(p)}" for p in _own_required_perms(command)) or "n/a"
        embed.add_field(name="Aliases", value=aliases, inline=True)
        embed.add_field(name="Parameters", value=params, inline=True)
        embed.add_field(name="Information", value=perms, inline=True)

        usage = f"Syntax: {_syntax(prefix, command)}\nExample: {_example(prefix, command)}"
        embed.add_field(name="Usage", value=f"```\n{usage}\n```", inline=False)

        category = getattr(command.cog, "category", None) or "General"
        embed.set_footer(text=f"Página {number}/{total} ({total} entradas) • Módulo: {category}")
        return embed

    def command_pages(self, ctx: Context, command: commands.Command) -> List[discord.Embed]:
        """Una página para el comando y una por cada subcomando (recursivo)."""
        entries = _walk(command)
        return [self._command_page(ctx, cmd, i, len(entries)) for i, cmd in enumerate(entries, 1)]

    async def show(self, ctx: Context, command: commands.Command) -> Optional[discord.Message]:
        """Muestra la ayuda paginada de un comando (úsalo desde grupos sin subcomando)."""
        return await paginate(ctx, self.command_pages(ctx, command), always_buttons=True)

    # ------------------------------------------------------------------
    # Comando
    # ------------------------------------------------------------------
    @commands.command(name="help", aliases=["h", "ayuda", "commands"], usage="[categoría | comando]")
    async def help(self, ctx: Context, *, query: Optional[str] = None):
        """Muestra las categorías, los comandos de una categoría o el detalle de un comando."""
        categories = self._categories()
        if not query:
            return await ctx.send(embed=self._overview(ctx, categories))

        key = strip_accents(query).lower().strip()
        for name, cmds in categories.items():
            if strip_accents(name).lower() == key:
                lines = [f"`{c.qualified_name}` — {c.short_doc or 'Sin descripción'}" for c in cmds]
                pages = make_pages(lines, title=f"{name} · {len(cmds)} comandos", per_page=12)
                return await paginate(ctx, pages, always_buttons=True)

        command = self.bot.get_command(query.lower().strip())
        if command is None or command.hidden:
            raise BotError(f"No encontré ninguna categoría ni comando que coincida con `{truncate(query, 40)}`.")
        await self.show(ctx, command)


async def setup(bot) -> None:
    await bot.add_cog(Help(bot))
