"""Clase principal del bot."""
from __future__ import annotations

import json
import logging
import time
from typing import Dict

import discord
from discord.ext import commands

from config import BASE_DIR, DB_PATH, DEFAULT_PREFIX, OWNER_IDS
from core import embeds
from core.context import Context
from core.db import Database
from core.emojis import emojis

log = logging.getLogger("bot")

# El bot no se conecta a canales de voz (solo mueve/silencia miembros), así que
# no necesita PyNaCl ni davey: silenciamos esos avisos de discord.py.
discord.VoiceClient.warn_nacl = False
discord.VoiceClient.warn_dave = False


async def _get_prefix(bot: "Bot", message: discord.Message):
    prefix = DEFAULT_PREFIX
    if message.guild is not None:
        prefix = bot.prefixes.get(message.guild.id, DEFAULT_PREFIX)
    return commands.when_mentioned_or(prefix)(bot, message)


class Bot(commands.Bot):
    def __init__(self) -> None:
        # Necesitas activar "Server Members Intent" y "Message Content Intent"
        # en Discord Developer Portal -> tu aplicación -> Bot -> Privileged Gateway Intents.
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix=_get_prefix,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True,
            owner_ids=OWNER_IDS,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=False
            ),
            activity=discord.Activity(type=discord.ActivityType.watching, name=f"{DEFAULT_PREFIX}help"),
        )
        self.db = Database(DB_PATH)
        self.prefixes: Dict[int, str] = {}
        self.started_at: float = time.time()

    async def setup_hook(self) -> None:
        await self.db.connect()
        rows = await self.db.fetchall("SELECT guild_id, value FROM settings WHERE key = 'prefix'")
        self.prefixes = {row["guild_id"]: json.loads(row["value"]) for row in rows}
        await self.load_cogs()

    async def load_cogs(self) -> None:
        """Carga todos los archivos de cogs/ (menos los que empiezan con _)."""
        loaded = 0
        for path in sorted((BASE_DIR / "cogs").glob("*.py")):
            if path.stem.startswith("_"):
                continue
            try:
                await self.load_extension(f"cogs.{path.stem}")
                loaded += 1
            except Exception:
                log.exception("No se pudo cargar el cog %s", path.stem)
        log.info("Cogs cargados: %d", loaded)

    async def get_context(self, origin, *, cls=Context):
        return await super().get_context(origin, cls=cls)

    async def on_ready(self) -> None:
        log.info("Conectado como %s (%s) en %d servidores", self.user, self.user.id, len(self.guilds))
        await emojis.refresh(self)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if self.user and message.content.strip() in (f"<@{self.user.id}>", f"<@!{self.user.id}>"):
            prefix = DEFAULT_PREFIX
            if message.guild is not None:
                prefix = self.prefixes.get(message.guild.id, DEFAULT_PREFIX)
            try:
                await message.channel.send(
                    embed=embeds.neutral(f"Mi prefijo aquí es `{prefix}` · usa `{prefix}help` para ver los comandos.")
                )
            except discord.HTTPException:
                pass
            return
        await self.process_commands(message)

    async def close(self) -> None:
        await self.db.close()
        await super().close()
