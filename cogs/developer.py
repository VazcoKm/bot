"""Comandos solo para los dueños del bot (ocultos en help)."""
from __future__ import annotations

from typing import Optional

from discord.ext import commands

from core.cog import BaseCog
from core.context import Context
from core.emojis import FALLBACKS, emojis, normalize_emoji
from core.errors import BotError
from core.views import make_pages, paginate


class Developer(BaseCog):
    guild_only = False

    async def cog_check(self, ctx: Context) -> bool:
        return await self.bot.is_owner(ctx.author)

    @commands.command(name="reload", aliases=["rl"], hidden=True, usage="[módulo | all]")
    async def reload(self, ctx: Context, module: Optional[str] = None):
        """Recarga un cog sin reiniciar el bot (o todos con `all`)."""
        if module is None or module.lower() == "all":
            names = [ext.split(".")[-1] for ext in list(self.bot.extensions)]
        else:
            names = [module.lower()]
        done, failed = [], []
        for name in names:
            try:
                await self.bot.reload_extension(f"cogs.{name}")
                done.append(name)
            except commands.ExtensionNotLoaded:
                try:
                    await self.bot.load_extension(f"cogs.{name}")
                    done.append(name)
                except Exception as exc:  # noqa: BLE001
                    failed.append(f"{name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{name}: {exc}")
        if failed:
            await ctx.deny("Fallaron:\n" + "\n".join(f"`{f[:200]}`" for f in failed))
        if done:
            await ctx.approve(f"Recargados: {', '.join(f'`{n}`' for n in done)}")

    @commands.group(name="botemoji", hidden=True, invoke_without_command=True)
    async def botemoji(self, ctx: Context):
        """Gestiona los emojis del bot (list / set / reset)."""
        await ctx.invoke(self.botemoji_list)

    @botemoji.command(name="list", hidden=True)
    async def botemoji_list(self, ctx: Context):
        """Lista los nombres de emoji y su valor actual."""
        lines = [f"`{name}` → {emojis.get(name)}" for name in emojis.names()]
        await paginate(ctx, make_pages(lines, title="Emojis del bot", per_page=15))

    @botemoji.command(name="check", hidden=True)
    async def botemoji_check(self, ctx: Context):
        """Comprueba qué emojis personalizados puede usar el bot en los botones."""
        status = await emojis.refresh(self.bot)
        lines = []
        for name, ok in status.items():
            note = "accesible" if ok else "**no accesible**" + (f" (en botones usa {FALLBACKS[name]})" if name in FALLBACKS else "")
            lines.append(f"`{name}` {emojis.get(name)} — {note}")
        await paginate(ctx, make_pages(lines, title="Emojis personalizados", per_page=15))

    @botemoji.command(name="set", hidden=True, usage="<nombre> <emoji>")
    async def botemoji_set(self, ctx: Context, name: str, emoji: str):
        """Cambia un emoji. Acepta el emoji, su ID o su URL del CDN de Discord."""
        name = name.lower()
        if name not in emojis.names():
            raise BotError("Ese nombre no existe. Usa `botemoji list` para ver los disponibles.")
        value = normalize_emoji(emoji)
        emojis.set(name, value)
        await emojis.refresh(self.bot)
        await ctx.approve(f"`{name}` ahora es {value}")

    @botemoji.command(name="reset", hidden=True, usage="<nombre>")
    async def botemoji_reset(self, ctx: Context, name: str):
        """Devuelve un emoji a su valor por defecto."""
        name = name.lower()
        if name not in emojis.names():
            raise BotError("Ese nombre no existe. Usa `botemoji list` para ver los disponibles.")
        emojis.reset(name)
        await ctx.approve(f"`{name}` restablecido a {emojis.get(name)}")


async def setup(bot) -> None:
    await bot.add_cog(Developer(bot))
