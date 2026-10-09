"""Mide el progreso: carga todos los cogs SIN conectarse a Discord y cuenta los comandos.

    python check.py

Úsalo después de añadir comandos: te dice cuántos llevas por categoría y detecta
errores de carga (alias repetidos, sintaxis, imports rotos) antes de arrancar el bot.
"""
import asyncio
import logging
from collections import defaultdict

from core.bot import Bot

META = 300  # objetivo total de comandos


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    async with Bot() as bot:
        await bot.load_cogs()
        if not bot.cogs:
            print("No se cargó ningún cog.")
            return

        per_category = defaultdict(int)
        hidden = 0
        for command in bot.walk_commands():
            category = getattr(command.cog, "category", None)
            if command.hidden:
                hidden += 1
            elif category:
                per_category[category] += 1

        total = sum(per_category.values())
        print(f"\nCogs cargados: {len(bot.cogs)}  |  extensiones: {len(bot.extensions)}\n")
        width = max((len(name) for name in per_category), default=10)
        for name, count in sorted(per_category.items(), key=lambda kv: -kv[1]):
            print(f"  {name:<{width}}  {count:>3}")
        print(f"\n  {'TOTAL':<{width}}  {total:>3} / {META}   ({total / META:.0%})")
        print(f"  (+{hidden} comandos ocultos de desarrollador)\n")


if __name__ == "__main__":
    asyncio.run(main())
