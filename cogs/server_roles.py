"""Servidor · roles: dar y quitar roles (acepta menciones, IDs y nombres parciales)."""
from __future__ import annotations

import discord
from discord.ext import commands

from core import cases, checks
from core.cog import BaseCog
from core.context import Context
from core.converters import FuzzyRole
from core.emojis import emojis


class ServerRoles(BaseCog):
    """Gestión de roles de miembros."""

    category = "Servidor"

    @commands.group(name="role", aliases=["r"], invoke_without_command=True, usage="<miembro> <rol>")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role(self, ctx: Context, member: discord.Member, *, role: FuzzyRole):
        """Añade o quita un rol a un miembro: si ya lo tiene, se lo quita."""
        checks.ensure_hierarchy(ctx, member, "moderar", allow_self=True)
        checks.ensure_role_manageable(ctx, role)
        reason = cases.audit_reason(ctx.author, "role")
        if role in member.roles:
            await member.remove_roles(role, reason=reason)
            await ctx.approve(f"Se quitó {role.mention} de {member.mention}.", emoji=emojis.remove)
        else:
            await member.add_roles(role, reason=reason)
            await ctx.approve(f"Se añadió {role.mention} a {member.mention}.", emoji=emojis.plus)

    @role.command(name="add", aliases=["give"], usage="<miembro> <rol>")
    async def role_add(self, ctx: Context, member: discord.Member, *, role: FuzzyRole):
        """Añade un rol a un miembro."""
        checks.ensure_hierarchy(ctx, member, "moderar", allow_self=True)
        checks.ensure_role_manageable(ctx, role)
        if role in member.roles:
            await ctx.warn(f"{member.mention} ya tiene {role.mention}.")
            return
        await member.add_roles(role, reason=cases.audit_reason(ctx.author, "role add"))
        await ctx.approve(f"Se añadió {role.mention} a {member.mention}.", emoji=emojis.plus)

    @role.command(name="remove", aliases=["take"], usage="<miembro> <rol>")
    async def role_remove(self, ctx: Context, member: discord.Member, *, role: FuzzyRole):
        """Quita un rol a un miembro."""
        checks.ensure_hierarchy(ctx, member, "moderar", allow_self=True)
        checks.ensure_role_manageable(ctx, role)
        if role not in member.roles:
            await ctx.warn(f"{member.mention} no tiene {role.mention}.")
            return
        await member.remove_roles(role, reason=cases.audit_reason(ctx.author, "role remove"))
        await ctx.approve(f"Se quitó {role.mention} de {member.mention}.", emoji=emojis.remove)


async def setup(bot) -> None:
    await bot.add_cog(ServerRoles(bot))
