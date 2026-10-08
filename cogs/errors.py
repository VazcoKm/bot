"""Manejo global de errores, con el estilo de Greed.

- Errores de uso (falta un argumento, no encontrado, sin permiso)  -> embed ámbar con ⚠
- Acciones que se intentaron y fallaron                              -> embed rojo con ✖
Los nombres de parámetros y permisos van en `código`, y las palabras clave en **negrita**.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from core.cog import BaseCog
from core.context import Context
from core.errors import BotError
from core.utils import param_name, perm_name, truncate

log = logging.getLogger("bot.errors")


def _perms(names) -> str:
    return ", ".join(f"`{perm_name(p).lower()}`" for p in names)


class ErrorHandler(BaseCog):
    guild_only = False

    @staticmethod
    async def _send(ctx: Context, kind: str, text: str) -> None:
        try:
            await (ctx.deny if kind == "error" else ctx.warn)(text)
        except discord.HTTPException:
            pass  # sin permiso para escribir: no hay nada más que hacer

    @commands.Cog.listener()
    async def on_command_error(self, ctx: Context, error: commands.CommandError) -> None:
        if hasattr(ctx.command, "on_error"):
            return
        if isinstance(error, (commands.CommandNotFound, commands.DisabledCommand)):
            return
        send = self._send

        if isinstance(error, BotError):
            return await send(ctx, error.kind, str(error))

        if isinstance(error, commands.MissingRequiredArgument):
            return await send(ctx, "warn", f"Debes indicar `{param_name(error.param.name)}`.")

        if isinstance(error, commands.MissingPermissions):
            return await send(ctx, "warn", f"Te **falta** el permiso: {_perms(error.missing_permissions)}")

        if isinstance(error, commands.BotMissingPermissions):
            return await send(ctx, "warn", f"Me **falta** el permiso: {_perms(error.missing_permissions)}")

        if isinstance(error, commands.NoPrivateMessage):
            return await send(ctx, "warn", "Este comando solo se puede usar en un **servidor**.")

        if isinstance(error, commands.CommandOnCooldown):
            return await send(ctx, "warn", f"Espera **{error.retry_after:.1f}s** para volver a usar este comando.")

        if isinstance(error, commands.MemberNotFound):
            return await send(ctx, "warn", f"No encontré a ningún miembro que coincida con `{truncate(error.argument, 40)}`.")
        if isinstance(error, commands.UserNotFound):
            return await send(ctx, "warn", f"No encontré a ningún usuario que coincida con `{truncate(error.argument, 40)}`.")
        if isinstance(error, commands.ChannelNotFound):
            return await send(ctx, "warn", f"No encontré ningún canal que coincida con `{truncate(error.argument, 40)}`.")
        if isinstance(error, commands.RoleNotFound):
            return await send(ctx, "warn", f"No encontré ningún rol que coincida con `{truncate(error.argument, 40)}`.")

        if isinstance(error, commands.UserInputError):  # BadArgument, BadUnionArgument...
            name = ctx.command.qualified_name if ctx.command else "comando"
            return await send(ctx, "warn", f"Argumento inválido. Mira `{ctx.clean_prefix}help {name}`.")

        if isinstance(error, commands.CheckFailure):
            if ctx.command is not None and ctx.command.hidden:
                return  # comandos de desarrollador: no delatar que existen
            return await send(ctx, "warn", "No puedes usar este comando.")

        original = error.original if isinstance(error, commands.CommandInvokeError) else error

        if isinstance(original, discord.Forbidden):
            return await send(ctx, "error", "No tengo permisos para hacer eso. Revisa mi rol y la jerarquía de roles.")
        if isinstance(original, discord.NotFound):
            return await send(ctx, "error", "No encontré eso en Discord (¿ya fue eliminado?).")
        if isinstance(original, discord.HTTPException):
            return await send(ctx, "error", f"Discord rechazó la acción: `{truncate(original.text, 150)}`")

        log.error("Error inesperado en el comando %s", ctx.command, exc_info=original)
        await send(ctx, "error", "Ocurrió un error inesperado. Ya quedó registrado en la consola.")


async def setup(bot) -> None:
    await bot.add_cog(ErrorHandler(bot))
