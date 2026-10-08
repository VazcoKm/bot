"""Errores propios del bot."""
from discord.ext import commands


class BotError(commands.CommandError):
    """Error con un mensaje listo para mostrarle al usuario.

    kind="warn"  -> embed ámbar (errores de uso: falta un argumento, no encontrado, sin permiso)
    kind="error" -> embed rojo con ✖ (la acción se intentó y falló: "No se pudo desbanear.")
    """

    def __init__(self, message: str, *, kind: str = "warn") -> None:
        super().__init__(message)
        self.kind = kind
