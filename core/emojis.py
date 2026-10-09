"""Emojis del bot.

Ningún comando escribe emojis sueltos: todos usan `emojis.success`, `emojis.ban`, etc.
Cuando subas tus emojis, sobrescribe los valores en `emojis.json` (copia
`emojis.example.json`) o usa el comando de owner `botemoji set <nombre> <emoji>`.
Cambian en todo el bot al instante, sin tocar ningún comando.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Set

from config import EMOJI_FILE

log = logging.getLogger("bot.emojis")

DEFAULTS: Dict[str, str] = {
    # --- Tus emojis personalizados (el bot debe estar en el servidor que los aloja,
    #     o súbelos como "Application Emojis" en el Developer Portal) ---
    "success": "<:aprovve:1556558143117459476>",
    "error": "<:cross:1556555143892303942>",
    "warn": "<:warning:1556555096874160148>",
    "plus": "<:add:1556555064397660230>",
    "remove": "<:remove:1557155852211978240>",
    "prev": "<:arrow:1556558190525816923>",
    "next": "<:arrow:1556555821217878056>",
    "search": "<:search:1556860870389145681>",
    "close": "<:quitx:1557165959926648842>",
    "confirm": "<:aprovve:1556558143117459476>",
    "cancel": "<:cross:1556555143892303942>",
    # --- Otros estados ---
    "info": "ℹ️",
    "loading": "⏳",
    "wave": "👋",
    # --- Moderación ---
    "case": "📁",
    "ban": "🔨",
    "unban": "♻️",
    "kick": "👢",
    "softban": "🧹",
    "tempban": "⏳",
    "mute": "🔇",
    "unmute": "🔊",
    "jail": "⛓️",
    "unjail": "🗝️",
    "lock": "🔒",
    "unlock": "🔓",
    "hide": "🙈",
    "unhide": "👁️",
    "purge": "🧽",
    "nuke": "💥",
    "slowmode": "🐢",
    "voice": "🎙️",
    # --- VoiceMaster (botones de la interfaz, en el orden de tu captura) ---
    "vm_lock": "<:vm_lock:1557506611650629725>",
    "vm_unlock": "<:vm_unlock:1557506675689394326>",
    "vm_ghost": "<:vm_ghost:1557506762486063165>",
    "vm_reveal": "<:vm_reveal:1557506813145129131>",
    "vm_claim": "<:vm_claim:1557506915821559868>",
    "vm_info": "<:vm_info:1557507208982569040>",
    "vm_plus": "<:vm_plus:1557506988777279508>",
    "vm_minus": "<:vm_minus:1557507076861730866>",
    "vm_rename": "<:vm_rename:1557506862335664239>",
    "vm_delete": "<:vm_delete:1557507147334688828>",
    # --- Utilidad ---
    "poll_yes": "👍",
    "poll_no": "👎",
    "afk": "💤",
    "remind": "⏰",
}


# Emojis normales que se usan en los BOTONES cuando el emoji personalizado no es accesible para el bot.
# (Discord valida los emojis de los botones: uno inexistente o de un servidor al que el bot no
# pertenece hace fallar el mensaje entero con "Invalid emoji".)
FALLBACKS: Dict[str, str] = {
    "prev": "◀️",
    "next": "▶️",
    "search": "🔍",
    "close": "🚫",
    "confirm": "✅",
    "cancel": "❌",
    "vm_lock": "🔒",
    "vm_unlock": "🔓",
    "vm_ghost": "👻",
    "vm_reveal": "👁️",
    "vm_claim": "👑",
    "vm_info": "📄",
    "vm_plus": "➕",
    "vm_minus": "➖",
    "vm_rename": "✏️",
    "vm_delete": "🗑️",
}
_CUSTOM = re.compile(r"^<a?:\w+:(\d+)>$")
_CDN = re.compile(r"emojis/(\d{15,25})\.(\w+)")


def normalize_emoji(value: str) -> str:
    """Convierte un ID, una URL del CDN de Discord o un emoji ya formateado en algo que el bot pueda enviar.

    '1556555064397660230'                                  -> '<:e:1556555064397660230>'
    'https://cdn.discordapp.com/emojis/155...230.webp?...' -> '<:e:155...230>'   (.gif -> animado)
    '<:check:155...230>' o un emoji unicode                -> se deja igual
    """
    text = value.strip()
    if text.startswith("<") and text.endswith(">"):
        return text
    match = _CDN.search(text)
    if match:
        animated = match.group(2).lower() == "gif" or "animated=true" in text
        return f"<{'a' if animated else ''}:e:{match.group(1)}>"
    if text.isdigit() and len(text) >= 15:
        return f"<:e:{text}>"
    return text


class EmojiManager:
    def __init__(self) -> None:
        self._overrides: Dict[str, str] = {}
        self.known_ids: Optional[Set[int]] = None  # IDs que el bot puede usar; None = sin comprobar
        self.reload()

    def reload(self) -> None:
        self._overrides = {}
        if EMOJI_FILE.exists():
            try:
                data = json.loads(EMOJI_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._overrides = {str(k): str(v) for k, v in data.items() if v}
            except (OSError, ValueError):
                pass

    def _save(self) -> None:
        EMOJI_FILE.write_text(
            json.dumps(self._overrides, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get(self, name: str, default: str = "") -> str:
        return self._overrides.get(name) or DEFAULTS.get(name, default)

    def __getattr__(self, name: str) -> str:
        if name.startswith("_"):
            raise AttributeError(name)
        value = self.get(name)
        if not value:
            raise AttributeError(f"El emoji '{name}' no existe en core/emojis.py")
        return value

    def button(self, name: str) -> str:
        """Emoji para un botón: el personalizado si el bot lo puede usar; si no, uno normal."""
        value = self.get(name)
        match = _CUSTOM.match(value)
        if match and self.known_ids is not None and int(match.group(1)) not in self.known_ids:
            return FALLBACKS.get(name, "▫️")
        return value

    def fallback(self, name: str) -> str:
        return FALLBACKS.get(name, self.get(name))

    async def refresh(self, bot) -> Dict[str, bool]:
        """Mira qué emojis personalizados puede usar el bot (de sus servidores y de la aplicación).

        Devuelve {nombre: accesible} solo para los emojis personalizados en uso.
        """
        known = {emoji.id for emoji in bot.emojis}
        if hasattr(bot, "fetch_application_emojis"):
            try:
                known |= {emoji.id for emoji in await bot.fetch_application_emojis()}
            except Exception:  # noqa: BLE001 - sin permiso o versión antigua: seguimos con los de servidor
                pass
        self.known_ids = known
        result: Dict[str, bool] = {}
        for name in DEFAULTS:
            match = _CUSTOM.match(self.get(name))
            if match:
                result[name] = int(match.group(1)) in known
        missing = [name for name, ok in result.items() if not ok]
        if missing:
            log.warning(
                "El bot no puede usar estos emojis personalizados: %s. En los botones usará emojis normales. "
                "Mete al bot en el servidor que los aloja o súbelos como emojis de la aplicación.",
                ", ".join(missing),
            )
        return result

    def set(self, name: str, value: str) -> None:
        self._overrides[name] = value
        self._save()

    def reset(self, name: str) -> None:
        self._overrides.pop(name, None)
        self._save()

    def names(self) -> List[str]:
        return sorted(DEFAULTS)


emojis = EmojiManager()
