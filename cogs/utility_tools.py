"""Utilidad · herramientas: snipe, afk, recordatorios, todo, calculadora, dados, encuestas..."""
from __future__ import annotations

import ast
import datetime as dt
import math
import operator
import random
import re
import time
import zoneinfo
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple, Union

import discord
from discord.ext import commands, tasks

from config import Colors
from core import cases, embeds
from core.cog import BaseCog
from core.context import Context
from core.converters import Duration
from core.emojis import emojis
from core.errors import BotError
from core.utils import format_timedelta, humanize_seconds, truncate
from core.views import make_pages, paginate

# ----------------------------------------------------------------------
# Calculadora segura (sin eval): solo números, operadores y funciones permitidas
# ----------------------------------------------------------------------
_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log,
    "log10": math.log10, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_eval(expression: str) -> Union[int, float]:
    """Evalúa una expresión matemática. Lanza ValueError si no es válida o es demasiado grande."""
    text = expression.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    if not text or len(text) > 200:
        raise ValueError("expresión vacía o demasiado larga")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise ValueError("sintaxis inválida")

    def walk(node: ast.AST, depth: int = 0) -> Union[int, float]:
        if depth > 30:
            raise ValueError("expresión demasiado anidada")
        if isinstance(node, ast.Expression):
            return walk(node.body, depth + 1)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](walk(node.operand, depth + 1))
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = walk(node.left, depth + 1), walk(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and (abs(right) > 1000 or (abs(left) > 1e6 and abs(right) > 50)):
                raise ValueError("potencia demasiado grande")
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[walk(arg, depth + 1) for arg in node.args])
        raise ValueError("operación no permitida")

    try:
        return walk(tree)
    except (ZeroDivisionError, OverflowError):
        raise ValueError("división entre cero o número demasiado grande")
    except TypeError:
        raise ValueError("argumentos inválidos")


DICE_RE = re.compile(r"^(\d{1,3})?d(\d{1,4})([+-]\d{1,5})?$", re.I)
EIGHT_BALL = [
    "Sí, sin duda.", "Todo apunta a que sí.", "Es muy probable.", "Las señales dicen que sí.",
    "Pregunta de nuevo más tarde.", "Mejor no decírtelo ahora.", "No puedo predecirlo.",
    "No cuentes con ello.", "Mi respuesta es no.", "Muy dudoso.",
]


def roll_dice(spec: str) -> Tuple[int, list, int]:
    """'2d6+3' -> (total, [tiradas], modificador). Lanza ValueError si no es válido."""
    match = DICE_RE.match(spec.strip().replace(" ", ""))
    if match is None:
        raise ValueError("formato inválido")
    count, sides, mod = int(match.group(1) or 1), int(match.group(2)), int(match.group(3) or 0)
    if not 1 <= count <= 100 or not 2 <= sides <= 1000:
        raise ValueError("fuera de rango")
    rolls = [random.randint(1, sides) for _ in range(count)]
    return sum(rolls) + mod, rolls, mod


class UtilityTools(BaseCog):
    """Snipe, AFK, recordatorios, todo, calculadora, dados y más."""

    category = "Utilidad"

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self.deleted: Dict[int, Deque[dict]] = defaultdict(lambda: deque(maxlen=10))
        self.edited: Dict[int, Deque[dict]] = defaultdict(lambda: deque(maxlen=10))
        self.afk_cache: Dict[Tuple[int, int], Tuple[str, float]] = {}
        self._afk_loaded = False

    async def cog_load(self) -> None:
        self.check_reminders.start()

    async def cog_unload(self) -> None:
        self.check_reminders.cancel()

    # ------------------------------------------------------------------
    # Snipe
    # ------------------------------------------------------------------
    @staticmethod
    def _snap(message: discord.Message) -> dict:
        return {
            "author": message.author.display_name,
            "avatar": message.author.display_avatar.url,
            "content": message.content,
            "files": [a.url for a in message.attachments],
            "at": discord.utils.utcnow(),
        }

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if message.content or message.attachments:
            self.deleted[message.channel.id].appendleft(self._snap(message))

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        self.edited[before.channel.id].appendleft(self._snap(before))

    @staticmethod
    def _snipe_embed(ctx: Context, entry: dict, label: str, number: int, total: int) -> discord.Embed:
        """Autor arriba, texto, y pie con tu avatar: 'Eliminado hace 5 segundos • 1/3 mensajes'."""
        embed = discord.Embed(description=truncate(entry["content"] or "(sin texto)", 1500), color=Colors.TAN)
        embed.set_author(name=entry["author"], icon_url=entry["avatar"])
        if entry["files"]:
            embed.add_field(name="Archivos", value="\n".join(entry["files"][:5]), inline=False)
        ago = humanize_seconds((discord.utils.utcnow() - entry["at"]).total_seconds())
        embed.set_footer(
            text=f"{label} hace {ago} • {number}/{total} mensajes",
            icon_url=ctx.author.display_avatar.url,
        )
        return embed

    @commands.command(name="snipe", aliases=["s"], usage="[número]")
    async def snipe(self, ctx: Context, number: int = 1):
        """Muestra el último mensaje eliminado del canal (hasta 10 recientes)."""
        items = self.deleted[ctx.channel.id]
        if not items:
            raise BotError("No se encontraron mensajes eliminados en este canal.")
        if not 1 <= number <= len(items):
            raise BotError(f"Elige un número entre **1** y **{len(items)}**.")
        await ctx.send(embed=self._snipe_embed(ctx, items[number - 1], "Eliminado", number, len(items)))

    @commands.command(name="editsnipe", aliases=["es"], usage="[número]")
    async def editsnipe(self, ctx: Context, number: int = 1):
        """Muestra la versión anterior del último mensaje editado del canal."""
        items = self.edited[ctx.channel.id]
        if not items:
            raise BotError("No se encontraron mensajes editados en este canal.")
        if not 1 <= number <= len(items):
            raise BotError(f"Elige un número entre **1** y **{len(items)}**.")
        await ctx.send(embed=self._snipe_embed(ctx, items[number - 1], "Editado", number, len(items)))

    @commands.command(name="clearsnipe", aliases=["cs"])
    @commands.has_permissions(manage_messages=True)
    async def clearsnipe(self, ctx: Context):
        """Borra los mensajes guardados de snipe y editsnipe en este canal."""
        self.deleted.pop(ctx.channel.id, None)
        self.edited.pop(ctx.channel.id, None)
        await ctx.approve("Snipe de este canal limpiado.")

    # ------------------------------------------------------------------
    # AFK
    # ------------------------------------------------------------------
    async def _ensure_afk_loaded(self) -> None:
        if self._afk_loaded:
            return
        rows = await self.bot.db.fetchall("SELECT guild_id, user_id, reason, since FROM afk")
        self.afk_cache = {(r["guild_id"], r["user_id"]): (r["reason"], r["since"]) for r in rows}
        self._afk_loaded = True

    async def _clear_afk(self, guild_id: int, author: discord.abc.User, channel) -> None:
        """Quita el AFK y manda el 'bienvenido de vuelta' (barra gris + 👋)."""
        _, since = self.afk_cache.pop((guild_id, author.id))
        await self.bot.db.execute("DELETE FROM afk WHERE guild_id = ? AND user_id = ?", guild_id, author.id)
        away = humanize_seconds(time.time() - since)
        try:
            await channel.send(
                embed=embeds.custom(author, emojis.wave, f"**Bienvenido de vuelta**, estuviste fuera {away}", Colors.DEFAULT)
            )
        except discord.HTTPException:
            pass

    @commands.command(name="afk", aliases=["a", "away"], usage="[razón]")
    async def afk(self, ctx: Context, *, reason: Optional[str] = None):
        """Márcate como AFK: avisaré a quien te mencione y te quitaré el AFK al volver."""
        await self._ensure_afk_loaded()
        key = (ctx.guild.id, ctx.author.id)
        if key in self.afk_cache:  # igual que Greed: error y, acto seguido, te da la bienvenida
            await ctx.deny("Ya estás **AFK**")
            return await self._clear_afk(ctx.guild.id, ctx.author, ctx.channel)
        reason = truncate(reason or "AFK", 100)
        since = time.time()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO afk (guild_id, user_id, reason, since) VALUES (?, ?, ?, ?)",
            ctx.guild.id, ctx.author.id, reason, since,
        )
        self.afk_cache[key] = (reason, since)
        await ctx.approve(f"**Ahora estás AFK** con el estado: `{reason}`")

    async def _is_afk_command(self, message: discord.Message) -> bool:
        prefixes = await self.bot.get_prefix(message)
        prefixes = [prefixes] if isinstance(prefixes, str) else list(prefixes)
        content = await self.bot.resolve_alias(message) or message.content
        for prefix in prefixes:
            if content.startswith(prefix):
                words = content[len(prefix):].strip().lower().split()
                if words and words[0] == "afk":
                    return True
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        await self._ensure_afk_loaded()
        if not self.afk_cache:
            return
        guild_id = message.guild.id
        if (guild_id, message.author.id) in self.afk_cache and not await self._is_afk_command(message):
            await self._clear_afk(guild_id, message.author, message.channel)
        notices = []
        for user in message.mentions[:3]:
            entry = self.afk_cache.get((guild_id, user.id))
            if entry and user.id != message.author.id:
                notices.append(f"**{user.name}** está AFK: {entry[0]} — <t:{int(entry[1])}:R>")
        if notices:
            try:
                await message.channel.send(embed=embeds.warn(message.author, "\n".join(notices)), delete_after=15)
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------
    # Recordatorios
    # ------------------------------------------------------------------
    @tasks.loop(seconds=15)
    async def check_reminders(self) -> None:
        rows = await self.bot.db.fetchall("SELECT * FROM reminders WHERE remind_at <= ?", time.time())
        for row in rows:
            await self.bot.db.execute("DELETE FROM reminders WHERE id = ?", row["id"])
            embed = embeds.neutral(truncate(row["message"], 1800), title=f"{emojis.remind} Recordatorio")
            embed.set_footer(text=f"Creado hace {format_timedelta(time.time() - row['created_at'])}")
            channel = self.bot.get_channel(row["channel_id"]) if row["channel_id"] else None
            try:
                if channel is not None:
                    await channel.send(content=f"<@{row['user_id']}>", embed=embed)
                else:
                    user = await self.bot.fetch_user(row["user_id"])
                    await user.send(embed=embed)
            except discord.HTTPException:
                try:
                    user = await self.bot.fetch_user(row["user_id"])
                    await user.send(embed=embed)
                except discord.HTTPException:
                    pass

    @check_reminders.before_loop
    async def _before_reminders(self) -> None:
        await self.bot.wait_until_ready()

    @commands.command(name="remind", aliases=["remindme", "rm"], usage="<duración> <texto>")
    async def remind(self, ctx: Context, duration: Duration, *, text: str):
        """Te recuerda algo pasado un tiempo (mín. 10s, máx. 25 pendientes)."""
        seconds = duration.total_seconds()
        if seconds < 10:
            raise BotError("La duración mínima es de **10 segundos**.")
        row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE user_id = ?", ctx.author.id)
        if row["n"] >= 25:
            raise BotError("Ya tienes **25** recordatorios pendientes. Borra alguno con `reminders delete`.")
        remind_at = time.time() + seconds
        reminder_id = await self.bot.db.execute(
            "INSERT INTO reminders (user_id, guild_id, channel_id, message, remind_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ctx.author.id, ctx.guild.id, ctx.channel.id, truncate(text, 1500), remind_at, time.time(),
        )
        await ctx.approve(f"Te lo recordaré <t:{int(remind_at)}:R> · id `{reminder_id}`")

    @commands.group(name="reminders", aliases=["reminds"], invoke_without_command=True)
    async def reminders(self, ctx: Context):
        """Lista tus recordatorios pendientes."""
        rows = await self.bot.db.fetchall(
            "SELECT * FROM reminders WHERE user_id = ? ORDER BY remind_at", ctx.author.id
        )
        if not rows:
            raise BotError("No tienes recordatorios pendientes.")
        lines = [f"`{r['id']}` · <t:{int(r['remind_at'])}:R> — {truncate(r['message'], 80)}" for r in rows]
        await paginate(ctx, make_pages(lines, title=f"Tus recordatorios ({len(rows)})"))

    @reminders.command(name="delete", aliases=["remove", "del"], usage="<id>")
    async def reminders_delete(self, ctx: Context, reminder_id: int):
        """Borra un recordatorio tuyo por su id."""
        row = await self.bot.db.fetchone(
            "SELECT id FROM reminders WHERE id = ? AND user_id = ?", reminder_id, ctx.author.id
        )
        if row is None:
            raise BotError(f"No tienes ningún recordatorio con id `{reminder_id}`.")
        await self.bot.db.execute("DELETE FROM reminders WHERE id = ?", reminder_id)
        await ctx.approve(f"Recordatorio `{reminder_id}` eliminado.")

    @reminders.command(name="clear", aliases=["reset"])
    async def reminders_clear(self, ctx: Context):
        """Borra todos tus recordatorios."""
        row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE user_id = ?", ctx.author.id)
        if not row["n"]:
            raise BotError("No tienes recordatorios pendientes.")
        await self.bot.db.execute("DELETE FROM reminders WHERE user_id = ?", ctx.author.id)
        await ctx.approve(f"Se eliminaron **{row['n']}** recordatorios.")

    # ------------------------------------------------------------------
    # Todo
    # ------------------------------------------------------------------
    @commands.group(name="todo", aliases=["todos"], invoke_without_command=True)
    async def todo(self, ctx: Context):
        """Muestra tu lista de tareas personal."""
        rows = await self.bot.db.fetchall("SELECT * FROM todos WHERE user_id = ? ORDER BY id", ctx.author.id)
        if not rows:
            raise BotError(f"Tu lista está vacía. Añade algo con `{ctx.clean_prefix}todo add <texto>`.")
        lines = [f"`{i}.` {truncate(r['content'], 120)}" for i, r in enumerate(rows, 1)]
        await paginate(ctx, make_pages(lines, title=f"Tareas de {ctx.author.name} ({len(rows)})"))

    @todo.command(name="add", aliases=["new"], usage="<texto>")
    async def todo_add(self, ctx: Context, *, text: str):
        """Añade una tarea a tu lista (máx. 50)."""
        row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM todos WHERE user_id = ?", ctx.author.id)
        if row["n"] >= 50:
            raise BotError("Tu lista ya tiene **50** tareas.")
        await self.bot.db.execute(
            "INSERT INTO todos (user_id, content, created_at) VALUES (?, ?, ?)", ctx.author.id, truncate(text, 300), time.time()
        )
        await ctx.approve(f"Tarea añadida · tienes **{row['n'] + 1}**.")

    @todo.command(name="remove", aliases=["done", "delete"], usage="<número>")
    async def todo_remove(self, ctx: Context, number: int):
        """Quita una tarea por su número en la lista."""
        rows = await self.bot.db.fetchall("SELECT id FROM todos WHERE user_id = ? ORDER BY id", ctx.author.id)
        if not 1 <= number <= len(rows):
            raise BotError(f"Elige un número entre **1** y **{len(rows)}**." if rows else "Tu lista está vacía.")
        await self.bot.db.execute("DELETE FROM todos WHERE id = ?", rows[number - 1]["id"])
        await ctx.approve(f"Tarea **{number}** eliminada.")

    @todo.command(name="clear", aliases=["reset"])
    async def todo_clear(self, ctx: Context):
        """Vacía tu lista de tareas."""
        row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM todos WHERE user_id = ?", ctx.author.id)
        if not row["n"]:
            raise BotError("Tu lista ya está vacía.")
        await self.bot.db.execute("DELETE FROM todos WHERE user_id = ?", ctx.author.id)
        await ctx.approve(f"Se eliminaron **{row['n']}** tareas.")

    # ------------------------------------------------------------------
    # Calculadora, azar y texto
    # ------------------------------------------------------------------
    @commands.command(name="calc", aliases=["math", "calculate"], usage="<expresión>")
    async def calc(self, ctx: Context, *, expression: str):
        """Calculadora: + - * / // % ** ( ), pi, e, sqrt, sin, cos, tan, log, abs, round..."""
        try:
            result = safe_eval(expression)
        except ValueError as exc:
            raise BotError(f"No pude calcular eso: {exc}.")
        shown = f"{result:,}" if isinstance(result, int) else f"{result:,.10g}"
        await ctx.approve(f"`{truncate(expression, 80)}` = **{shown}**")

    @commands.command(name="choose", aliases=["pick"], usage="<opción 1 | opción 2 | ...>")
    async def choose(self, ctx: Context, *, options: str):
        """Elige entre opciones separadas por `|` (o por comas)."""
        parts = [p.strip() for p in (options.split("|") if "|" in options else options.split(","))]
        parts = [p for p in parts if p]
        if len(parts) < 2:
            raise BotError("Dame al menos dos opciones separadas por `|` o comas.")
        await ctx.approve(f"Elijo **{truncate(random.choice(parts), 200)}**")

    @commands.command(name="roll", usage="[dados, ej. 2d6+3]")
    async def roll(self, ctx: Context, dice: str = "1d6"):
        """Tira dados: `roll 2d6+3`, `roll d20`."""
        try:
            total, rolls, mod = roll_dice(dice)
        except ValueError:
            raise BotError("Usa el formato `NdM`, por ejemplo `2d6`, `d20` o `3d8+2` (hasta 100 dados de 1000 caras).")
        detail = f" ({', '.join(map(str, rolls[:20]))}{'…' if len(rolls) > 20 else ''}{f' {mod:+d}' if mod else ''})" if len(rolls) > 1 or mod else ""
        await ctx.approve(f"`{dice}` → **{total}**{detail}")

    @commands.command(name="coinflip", aliases=["flip"])
    async def coinflip(self, ctx: Context):
        """Lanza una moneda."""
        await ctx.approve(f"Salió **{random.choice(['cara', 'cruz'])}**")

    @commands.command(name="eightball", aliases=["8ball"], usage="<pregunta>")
    async def eightball(self, ctx: Context, *, question: str):
        """Pregúntale algo a la bola 8 mágica."""
        await ctx.approve(f"{random.choice(EIGHT_BALL)}")

    @commands.command(name="random", aliases=["rand"], usage="<mínimo> <máximo>")
    async def random_number(self, ctx: Context, low: int, high: int):
        """Número al azar entre dos valores (incluidos)."""
        if low > high:
            low, high = high, low
        await ctx.approve(f"Número entre `{low}` y `{high}`: **{random.randint(low, high)}**")

    @commands.command(name="poll", aliases=["vote"], usage="<duración> <pregunta> [| opción | opción]")
    @commands.bot_has_permissions(send_polls=True)
    async def poll(self, ctx: Context, duration: Duration, *, question: str):
        """Crea una encuesta nativa de Discord. Sin opciones usa Sí / No: `poll 5h ¿Quién es mejor? | Ana | Luis`."""
        hours = int(duration.total_seconds() // 3600)
        if not 1 <= hours <= 768:
            raise BotError("La duración de la encuesta debe estar entre **1h** y **32d**.")
        parts = [part.strip() for part in question.split("|")]
        title, options = parts[0], [o for o in parts[1:] if o] or ["Sí", "No"]
        if not title or len(title) > 300:
            raise BotError("La pregunta debe tener entre 1 y 300 caracteres.")
        if not 2 <= len(options) <= 10 or any(len(o) > 55 for o in options):
            raise BotError("Una encuesta lleva de 2 a 10 opciones, de máximo 55 caracteres cada una.")
        poll = discord.Poll(question=title, duration=dt.timedelta(hours=hours))
        for option in options:
            poll.add_answer(text=option)
        await ctx.send(poll=poll)

    # ------------------------------------------------------------------
    # Mensajes del bot, tiempo y pines
    # ------------------------------------------------------------------
    @commands.command(name="say", aliases=["echo"], usage="<texto>")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx: Context, *, text: str):
        """El bot envía un mensaje de texto (sin menciones masivas)."""
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send(truncate(text, 1900), allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="embed", aliases=["sayembed"], usage="<texto>")
    @commands.has_permissions(manage_messages=True)
    async def embed(self, ctx: Context, *, text: str):
        """El bot envía un mensaje dentro de un embed."""
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send(embed=embeds.neutral(truncate(text, 3900)), allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="timestamp", aliases=["ts"], usage="[duración]")
    async def timestamp(self, ctx: Context, duration: Optional[Duration] = None):
        """Códigos de timestamp de Discord para ahora o dentro de una duración (ej. `2h`)."""
        seconds = int(time.time() + (duration.total_seconds() if duration else 0))
        styles = (("t", "hora corta"), ("T", "hora"), ("d", "fecha corta"), ("D", "fecha"), ("f", "fecha y hora"), ("F", "completo"), ("R", "relativo"))
        lines = [f"`<t:{seconds}:{s}>` → <t:{seconds}:{s}> · {name}" for s, name in styles]
        await ctx.neutral("\n".join(lines), title=f"Timestamp {seconds}")

    @commands.command(name="time", aliases=["tz"], usage="<zona horaria>")
    async def time(self, ctx: Context, *, zone: str):
        """Hora actual en una zona horaria, ej. `time America/Monterrey`."""
        try:
            tz = zoneinfo.ZoneInfo(zone.strip().replace(" ", "_"))
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            raise BotError(f"No conozco la zona `{truncate(zone, 40)}`. Usa el formato `Continente/Ciudad`, ej. `Europe/Madrid`.")
        now = discord.utils.utcnow().astimezone(tz)
        await ctx.neutral(f"**{now:%H:%M}** · {now:%d/%m/%Y} · `{tz.key}` (UTC{now:%z})")

    @commands.command(name="pin", usage="[mensaje]")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def pin(self, ctx: Context, message: Optional[discord.Message] = None):
        """Fija un mensaje (responde a él o indica su ID / enlace)."""
        target = message or (ctx.message.reference.resolved if ctx.message.reference else None)
        if not isinstance(target, discord.Message):
            raise BotError("Responde a un mensaje o indica su ID.")
        await target.pin(reason=cases.audit_reason(ctx.author, "pin"))
        await ctx.approve(f"[Mensaje]({target.jump_url}) fijado.")

    @commands.command(name="unpin", usage="[mensaje]")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def unpin(self, ctx: Context, message: Optional[discord.Message] = None):
        """Desfija un mensaje (responde a él o indica su ID / enlace)."""
        target = message or (ctx.message.reference.resolved if ctx.message.reference else None)
        if not isinstance(target, discord.Message):
            raise BotError("Responde a un mensaje o indica su ID.")
        await target.unpin(reason=cases.audit_reason(ctx.author, "unpin"))
        await ctx.approve(f"[Mensaje]({target.jump_url}) desfijado.")


async def setup(bot) -> None:
    await bot.add_cog(UtilityTools(bot))
