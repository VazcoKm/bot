"""Utilidades pequeñas compartidas por todos los comandos."""
from __future__ import annotations

import datetime as dt
import unicodedata
from typing import Union

PERM_NAMES = {
    "administrator": "Administrador",
    "manage_guild": "Gestionar servidor",
    "manage_roles": "Gestionar roles",
    "manage_channels": "Gestionar canales",
    "manage_messages": "Gestionar mensajes",
    "manage_nicknames": "Gestionar apodos",
    "manage_webhooks": "Gestionar webhooks",
    "manage_expressions": "Gestionar expresiones",
    "manage_emojis_and_stickers": "Gestionar emojis y stickers",
    "manage_threads": "Gestionar hilos",
    "kick_members": "Expulsar miembros",
    "ban_members": "Banear miembros",
    "moderate_members": "Aislar miembros (timeout)",
    "mute_members": "Silenciar miembros",
    "deafen_members": "Ensordecer miembros",
    "move_members": "Mover miembros",
    "view_audit_log": "Ver registro de auditoría",
    "view_channel": "Ver canal",
    "send_messages": "Enviar mensajes",
    "embed_links": "Insertar enlaces",
    "read_message_history": "Ver historial de mensajes",
    "add_reactions": "Añadir reacciones",
    "mention_everyone": "Mencionar @everyone",
    "create_instant_invite": "Crear invitaciones",
    "send_polls": "Crear encuestas",
    "attach_files": "Adjuntar archivos",
    "connect": "Conectar",
    "speak": "Hablar",
}


PARAM_NAMES = {
    "user": "usuario", "users": "usuarios", "member": "miembro", "channel": "canal",
    "role": "rol", "amount": "cantidad", "duration": "duración", "reason": "razón",
    "new_reason": "razón", "number": "número", "case_id": "caso", "text": "texto",
    "nickname": "apodo", "source": "origen", "destination": "destino", "module": "módulo",
    "name": "nombre", "emoji": "emoji", "query": "búsqueda", "moderator": "moderador",
    "question": "pregunta", "server": "servidor", "message": "mensaje", "options": "opciones",
    "zone": "zona", "expression": "expresión", "dice": "dados", "low": "mínimo", "high": "máximo",
    "reminder_id": "id", "value": "valor", "invite": "invitación", "nickname": "apodo",
}


def param_name(name: str) -> str:
    """Nombre de un parámetro de comando tal como se le muestra al usuario."""
    return PARAM_NAMES.get(name, name)


def perm_name(perm: str) -> str:
    return PERM_NAMES.get(perm, perm.replace("_", " ").capitalize())


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def truncate(text: object, limit: int, suffix: str = "…") -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - len(suffix))] + suffix


def format_timedelta(delta: Union[dt.timedelta, int, float]) -> str:
    """90061 segundos -> '1d 1h 1m 1s'"""
    if isinstance(delta, (int, float)):
        delta = dt.timedelta(seconds=delta)
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "0s"
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value}{unit}")
    return " ".join(parts)


def humanize_seconds(seconds: float) -> str:
    """90 -> '1 minuto', 2 -> '2 segundos', 7300 -> '2 horas' (solo la unidad mayor)."""
    seconds = max(0, int(seconds))
    for size, one, many in ((86400, "día", "días"), (3600, "hora", "horas"), (60, "minuto", "minutos")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {one if n == 1 else many}"
    return f"{seconds} {'segundo' if seconds == 1 else 'segundos'}"
