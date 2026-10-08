"""Configuración central. Aquí cambias colores, nombre y valores por defecto."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

TOKEN: str = os.getenv("DISCORD_TOKEN", "").strip()
DEFAULT_PREFIX: str = os.getenv("DEFAULT_PREFIX", ",").strip() or ","
BOT_NAME: str = os.getenv("BOT_NAME", "Bot").strip() or "Bot"
OWNER_IDS: set[int] = {
    int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.isdigit()
}
DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data" / "bot.db"))
EMOJI_FILE: Path = BASE_DIR / "emojis.json"


class Colors:
    """Color de la barra lateral de los embeds (medidos de las capturas de Greed).

    El fondo oscuro del embed y su borde NO los controla el bot: los pinta tu tema de Discord.
    """

    DEFAULT = 0x3B3B3B  # gris de la barra en help y listas
    SUCCESS = 0x9FE878  # verde claro
    ERROR = 0xF86060  # rojo coral (fallos de ejecución)
    WARN = 0xF89E18  # ámbar (avisos y errores de uso)
    INFO = 0x3B3B3B
    TAN = 0xA3947B  # snipe y serverinfo
    GRAY = 0x84807E  # avatar, banner y userinfo
