"""Punto de entrada: `python main.py`"""
from config import TOKEN
from core.bot import Bot


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "Falta DISCORD_TOKEN. Copia .env.example a .env y pega el token de tu bot."
        )
    Bot().run(TOKEN)


if __name__ == "__main__":
    main()
