"""VoiceMaster: canales de voz temporales («join to create») con interfaz de botones.

Flujo: `,vc setup` crea la categoría VoiceMaster con el canal #interface y el hub «Join to Create».
Quien entra al hub recibe su propio canal de voz (y es su propietario); cuando queda vacío se borra.
El propietario lo controla con los botones de la interfaz o con los subcomandos de `,vc`.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Dict, Optional, Tuple, Union

import discord
from discord.ext import commands

from config import Colors
from core import cases
from core.cog import BaseCog
from core.context import Context
from core.emojis import emojis
from core.errors import BotError
from core.utils import truncate
from core.views import HAS_V2, _is_emoji_error, paginate_list

REGIONS = (
    "brazil", "hongkong", "india", "japan", "rotterdam", "russia", "singapore",
    "southafrica", "south-korea", "sydney", "us-central", "us-east", "us-south", "us-west",
)
DEFAULT_TEMPLATE = "Canal de {user}"
Result = Union[str, discord.Embed]


# ----------------------------------------------------------------------
# Respuestas privadas (como en Greed: solo las ve quien pulsó el botón)
# ----------------------------------------------------------------------
def _quote(text: str) -> discord.Embed:
    return discord.Embed(description=f"> {text}", color=Colors.TAN)


async def _reply(interaction: discord.Interaction, *, text: Optional[str] = None, embed: Optional[discord.Embed] = None) -> None:
    embed = embed or _quote(text or "")
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ----------------------------------------------------------------------
# Formularios
# ----------------------------------------------------------------------
class RenameModal(discord.ui.Modal, title="Renombrar"):
    new_name = discord.ui.TextInput(
        label="Renombra tu canal de voz", placeholder="ejemplo: Noche de películas", min_length=1, max_length=100
    )

    def __init__(self, cog: "VoiceMaster") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = str(self.new_name.value)
        await self.cog.run_interaction(interaction, lambda member: self.cog.op_rename(member, name))


class LimitModal(discord.ui.Modal):
    def __init__(self, cog: "VoiceMaster", direction: int) -> None:
        super().__init__(title="Aumentar límite de usuarios" if direction > 0 else "Reducir límite de usuarios")
        self.cog = cog
        self.direction = direction
        self.amount = discord.ui.TextInput(
            label="¿Cuántos usuarios quieres añadir?" if direction > 0 else "¿Cuántos usuarios quieres quitar?",
            placeholder="ejemplo: 1",
            default="1",
            min_length=1,
            max_length=2,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            number = int(str(self.amount.value).strip())
        except ValueError:
            return await _reply(interaction, text="Escribe un **número** válido.")
        if number < 1:
            return await _reply(interaction, text="El número debe ser **mayor a 0**.")
        delta = self.direction * number
        await self.cog.run_interaction(interaction, lambda member: self.cog.op_limit_change(member, delta))


# ----------------------------------------------------------------------
# Interfaz persistente (Components V2): contenedor con leyenda y 2 filas de 5 botones
# ----------------------------------------------------------------------
LEGEND = (
    ("vm_lock", "Bloquear", " el canal de voz"),
    ("vm_unlock", "Desbloquear", " el canal de voz"),
    ("vm_ghost", "Ocultar", " el canal de voz"),
    ("vm_reveal", "Revelar", " el canal de voz"),
    ("vm_rename", "Renombrar", ""),
    ("vm_claim", "Reclamar", " el canal de voz"),
    ("vm_plus", "Aumentar", " el límite de usuarios"),
    ("vm_minus", "Reducir", " el límite de usuarios"),
    ("vm_delete", "Eliminar", ""),
    ("vm_info", "Ver información", " del canal"),
)
GRID = (
    (("vm_lock", "lock"), ("vm_unlock", "unlock"), ("vm_ghost", "ghost"), ("vm_reveal", "reveal"), ("vm_claim", "claim")),
    (("vm_info", "info"), ("vm_plus", "plus"), ("vm_minus", "minus"), ("vm_rename", "rename"), ("vm_delete", "delete")),
)

if HAS_V2:

    class VoiceInterface(discord.ui.LayoutView):
        """Los botones usan custom_id fijos («vm:lock»...), así que siguen funcionando tras reiniciar el bot."""

        def __init__(self, thumbnail: Optional[str] = None, safe: bool = False) -> None:
            super().__init__(timeout=None)

            def emo(key: str) -> str:
                return emojis.fallback(key) if safe else emojis.button(key)

            legend = "\n".join(f"> {emo(key)} — `{label}`{rest}" for key, label, rest in LEGEND)
            usage = [discord.ui.TextDisplay("### Uso de los botones"), discord.ui.TextDisplay(legend)]
            usage_block = (
                [discord.ui.Section(*usage, accessory=discord.ui.Thumbnail(thumbnail))] if thumbnail else usage
            )
            rows = []
            for row in GRID:
                buttons = []
                for key, action in row:
                    button = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=emo(key), custom_id=f"vm:{action}")
                    button.callback = self._callback(action)
                    buttons.append(button)
                rows.append(discord.ui.ActionRow(*buttons))
            self.add_item(
                discord.ui.Container(
                    discord.ui.TextDisplay("## Interfaz de VoiceMaster"),
                    discord.ui.TextDisplay("-# Administra tu canal de voz con los botones de abajo."),
                    discord.ui.Separator(),
                    *usage_block,
                    discord.ui.Separator(),
                    *rows,
                    accent_colour=Colors.TAN,
                )
            )

        @staticmethod
        def _callback(action: str):
            async def callback(interaction: discord.Interaction) -> None:
                cog = interaction.client.get_cog("VoiceMaster")
                if cog is None or interaction.guild is None:
                    return await _reply(interaction, text="VoiceMaster no está disponible ahora mismo.")
                await cog.handle_button(interaction, action)

            return callback


# ----------------------------------------------------------------------
# Cog
# ----------------------------------------------------------------------
class VoiceMaster(BaseCog):
    """Canales de voz temporales (join to create)."""

    category = "Voicemaster"

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._last_create: Dict[int, float] = {}

    async def cog_load(self) -> None:
        if HAS_V2:
            self.bot.add_view(VoiceInterface())

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------
    @property
    def db(self):
        return self.bot.db

    @staticmethod
    def _why(member: discord.abc.User, text: str) -> str:
        return cases.audit_reason(member, f"voicemaster {text}")

    async def _own(self, member: discord.Member, *, need_owner: bool = True) -> Tuple[discord.VoiceChannel, object]:
        """El canal temporal en el que está `member` y su registro; exige ser el propietario si need_owner."""
        voice = getattr(member, "voice", None)
        if voice is None or voice.channel is None:
            raise BotError("Debes estar en tu **canal de voz** para usar esto.")
        row = await self.db.fetchone("SELECT * FROM vm_channels WHERE channel_id = ?", voice.channel.id)
        if row is None:
            raise BotError("Este **canal de voz** no es un canal temporal de VoiceMaster.")
        if need_owner and row["owner_id"] != member.id:
            raise BotError("No eres el **propietario** de este **canal de voz**.")
        return voice.channel, row

    async def _edit_overwrite(self, channel, target, reason: str, **changes) -> None:
        overwrite = channel.overwrites_for(target)
        overwrite.update(**changes)
        await channel.set_permissions(target, overwrite=None if overwrite.is_empty() else overwrite, reason=reason)

    async def _unregister(self, channel_id: int) -> None:
        await self.db.execute("DELETE FROM vm_channels WHERE channel_id = ?", channel_id)

    # ------------------------------------------------------------------
    # Interacciones (botones y formularios)
    # ------------------------------------------------------------------
    async def run_interaction(self, interaction: discord.Interaction, op: Callable[[discord.Member], Awaitable[Result]]) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            result = await op(interaction.user)
        except BotError as exc:
            return await _reply(interaction, text=str(exc))
        except discord.Forbidden:
            return await _reply(interaction, text="No tengo **permisos** para hacer eso en ese canal.")
        except discord.HTTPException as exc:
            return await _reply(interaction, text=f"Discord rechazó la acción: `{truncate(exc.text, 100)}`")
        await _reply(interaction, embed=result if isinstance(result, discord.Embed) else _quote(result))

    async def handle_button(self, interaction: discord.Interaction, action: str) -> None:
        if action in ("rename", "plus", "minus"):
            try:  # no enseñamos el formulario a quien no es propietario
                await self._own(interaction.user)
            except BotError as exc:
                return await _reply(interaction, text=str(exc))
            modal = RenameModal(self) if action == "rename" else LimitModal(self, 1 if action == "plus" else -1)
            return await interaction.response.send_modal(modal)
        operations = {
            "lock": self.op_lock, "unlock": self.op_unlock, "ghost": self.op_hide, "reveal": self.op_reveal,
            "claim": self.op_claim, "info": self.op_info, "delete": self.op_delete,
        }
        await self.run_interaction(interaction, operations[action])

    # ------------------------------------------------------------------
    # Operaciones (las usan los botones, los formularios y los comandos)
    # ------------------------------------------------------------------
    async def op_lock(self, member: discord.Member) -> str:
        channel, _ = await self._own(member)
        everyone = member.guild.default_role
        if channel.overwrites_for(everyone).connect is False:
            raise BotError("Tu **canal de voz** ya está **bloqueado**")
        await self._edit_overwrite(channel, everyone, self._why(member, "lock"), connect=False)
        return "Tu **canal de voz** ha sido **bloqueado**"

    async def op_unlock(self, member: discord.Member) -> str:
        channel, _ = await self._own(member)
        everyone = member.guild.default_role
        if channel.overwrites_for(everyone).connect is not False:
            raise BotError("Tu **canal de voz** ya **no está bloqueado**")
        await self._edit_overwrite(channel, everyone, self._why(member, "unlock"), connect=None)
        return "Tu **canal de voz** ha sido **desbloqueado**"

    async def op_hide(self, member: discord.Member) -> str:
        channel, _ = await self._own(member)
        everyone = member.guild.default_role
        if channel.overwrites_for(everyone).view_channel is False:
            raise BotError("Tu **canal de voz** ya está **oculto**")
        reason = self._why(member, "ghost")
        for present in channel.members:  # quien ya está dentro no debe perder el acceso al ocultarlo
            await self._edit_overwrite(channel, present, reason, view_channel=True)
        await self._edit_overwrite(channel, everyone, reason, view_channel=False)
        return "Tu **canal de voz** ha sido **ocultado**"

    async def op_reveal(self, member: discord.Member) -> str:
        channel, _ = await self._own(member)
        everyone = member.guild.default_role
        if channel.overwrites_for(everyone).view_channel is not False:
            raise BotError("Tu **canal de voz** ya **no está oculto**")
        await self._edit_overwrite(channel, everyone, self._why(member, "reveal"), view_channel=None)
        return "Tu **canal de voz** ha sido **revelado**"

    async def op_claim(self, member: discord.Member) -> str:
        channel, row = await self._own(member, need_owner=False)
        if row["owner_id"] == member.id:
            raise BotError("Ya eres el **propietario** de este **canal de voz**")
        owner = member.guild.get_member(row["owner_id"])
        if owner is not None and owner in channel.members:
            raise BotError("El propietario **sigue** en el **canal de voz**")
        await self.db.execute("UPDATE vm_channels SET owner_id = ? WHERE channel_id = ?", member.id, channel.id)
        await self._edit_overwrite(channel, member, self._why(member, "claim"), connect=True, view_channel=True, speak=True)
        return "Ahora eres el **propietario** de este **canal de voz**"

    async def op_info(self, member: discord.Member) -> discord.Embed:
        channel, row = await self._own(member, need_owner=False)
        owner = member.guild.get_member(row["owner_id"])
        lines = [
            f"> **Bitrate:** {channel.bitrate // 1000} KBPS",
            f"> **Miembros:** {len(channel.members)}",
            f"> **Creado:** {discord.utils.format_dt(discord.utils.snowflake_time(channel.id), 'D')}",
            f"> **Propietario:** {owner.mention if owner else '<@%d>' % row['owner_id']}",
        ]
        if channel.user_limit:
            lines.insert(2, f"> **Límite:** {channel.user_limit}")
        embed = discord.Embed(description="\n".join(lines), color=Colors.TAN)
        avatar = owner.display_avatar.url if owner else None
        embed.set_author(name=channel.name, icon_url=avatar)
        if avatar:
            embed.set_thumbnail(url=avatar)
        return embed

    async def op_limit_change(self, member: discord.Member, delta: int) -> str:
        channel, _ = await self._own(member)
        current = channel.user_limit or 0
        new = max(0, min(99, current + delta))
        if new == current:
            raise BotError("Tu **canal de voz** ya está en el límite máximo (**99**)" if delta > 0 else "Tu **canal de voz** ya no tiene **límite de usuarios**")
        await channel.edit(user_limit=new, reason=self._why(member, "limit"))
        if new == 0:
            return "Se ha **eliminado** el **límite de usuarios** en tu canal de voz (ilimitado)"
        verb = "aumentado" if delta > 0 else "reducido"
        return f"El **límite de usuarios de tu canal de voz** ha sido **{verb}** a `{new}`"

    async def op_limit_set(self, member: discord.Member, number: int) -> str:
        channel, _ = await self._own(member)
        if not 0 <= number <= 99:
            raise BotError("El límite debe estar entre **0** (ilimitado) y **99**.")
        await channel.edit(user_limit=number, reason=self._why(member, "limit"))
        if number == 0:
            return "Se ha **eliminado** el **límite de usuarios** en tu canal de voz (ilimitado)"
        return f"El **límite de usuarios de tu canal de voz** ha sido **establecido** en `{number}`"

    async def op_rename(self, member: discord.Member, name: str) -> str:
        channel, _ = await self._own(member)
        name = name.strip()[:100]
        if not name:
            raise BotError("El nombre no puede estar vacío.")
        try:  # Discord limita los cambios de nombre; sin tope de espera, la interacción moriría
            await asyncio.wait_for(channel.edit(name=name, reason=self._why(member, "rename")), timeout=8)
        except asyncio.TimeoutError:
            raise BotError("Discord limita los cambios de nombre (2 cada 10 minutos). Inténtalo más tarde.")
        return f"Tu **canal de voz** ha sido **renombrado** a **{discord.utils.escape_markdown(name)}**"

    async def op_delete(self, member: discord.Member) -> str:
        channel, _ = await self._own(member)
        await self._unregister(channel.id)
        await channel.delete(reason=self._why(member, "delete"))
        return "Tu **canal de voz** ha sido **eliminado**"

    async def op_permit(self, member: discord.Member, target: discord.Member) -> str:
        channel, _ = await self._own(member)
        await self._edit_overwrite(channel, target, self._why(member, "permit"), connect=True, view_channel=True)
        return f"{target.mention} ahora tiene **permiso** para entrar a tu **canal de voz**"

    async def op_reject(self, member: discord.Member, target: discord.Member) -> str:
        channel, _ = await self._own(member)
        if target.id == member.id:
            raise BotError("No puedes **rechazarte** a ti mismo.")
        await self._edit_overwrite(channel, target, self._why(member, "reject"), connect=False)
        if target in channel.members:
            await target.move_to(None, reason=self._why(member, "reject"))
        return f"{target.mention} ha sido **rechazado** de tu **canal de voz**"

    async def op_bitrate(self, member: discord.Member, kbps: int) -> str:
        channel, _ = await self._own(member)
        top = int(member.guild.bitrate_limit // 1000)
        if not 8 <= kbps <= top:
            raise BotError(f"El bitrate debe estar entre **8** y **{top}** kbps en este servidor.")
        await channel.edit(bitrate=kbps * 1000, reason=self._why(member, "bitrate"))
        return f"El **bitrate** de tu **canal de voz** ha sido **establecido** en `{kbps}` kbps"

    async def op_region(self, member: discord.Member, region: str) -> str:
        channel, _ = await self._own(member)
        region = region.lower().strip()
        if region in ("auto", "automatica", "automática"):
            await channel.edit(rtc_region=None, reason=self._why(member, "region"))
            return "La **región** de tu **canal de voz** ahora es **automática**"
        if region not in REGIONS:
            raise BotError("Región inválida. Opciones: `auto`, " + ", ".join(f"`{r}`" for r in REGIONS))
        await channel.edit(rtc_region=region, reason=self._why(member, "region"))
        return f"La **región** de tu **canal de voz** ahora es `{region}`"

    async def op_drag(self, member: discord.Member, target: discord.Member) -> str:
        channel, _ = await self._own(member)
        if target.voice is None or target.voice.channel is None:
            raise BotError(f"{target.mention} no está en un **canal de voz**.")
        if target.voice.channel.id == channel.id:
            raise BotError(f"{target.mention} ya está en tu **canal de voz**.")
        await target.move_to(channel, reason=self._why(member, "drag"))
        return f"{target.mention} ha sido **movido** a tu **canal de voz**"

    # ------------------------------------------------------------------
    # Eventos: crear y borrar canales temporales
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot:
            return
        if after.channel is not None and after.channel != before.channel:
            if await self.db.fetchone("SELECT 1 FROM vm_hubs WHERE channel_id = ?", after.channel.id):
                await self._create_temp(member, after.channel)
        if before.channel is not None and before.channel != after.channel:
            await self._cleanup(before.channel)

    async def _create_temp(self, member: discord.Member, hub: discord.VoiceChannel) -> None:
        now = time.monotonic()
        if now - self._last_create.get(member.id, 0.0) < 5:  # anti-spam: entrar y salir del hub sin parar
            try:
                await member.move_to(None, reason="VoiceMaster: demasiado rápido")
            except discord.HTTPException:
                pass
            return
        self._last_create[member.id] = now
        guild = member.guild
        template = await self.db.get_setting(guild.id, "vm_default_name", DEFAULT_TEMPLATE)
        name = (template.replace("{user}", member.display_name).strip() or f"Canal de {member.display_name}")[:100]
        overwrites = dict(hub.overwrites)
        overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        try:
            channel = await guild.create_voice_channel(
                name, category=hub.category, bitrate=hub.bitrate, user_limit=hub.user_limit,
                overwrites=overwrites, reason=f"VoiceMaster: canal de {member}",
            )
            await self.db.execute(
                "INSERT OR REPLACE INTO vm_channels (channel_id, guild_id, owner_id, created_at) VALUES (?, ?, ?, ?)",
                channel.id, guild.id, member.id, time.time(),
            )
            await member.move_to(channel, reason="VoiceMaster")
        except discord.HTTPException:
            if "channel" in locals():
                await self._cleanup(channel)
            return
        if not channel.members:  # se fue del hub antes de que lo moviéramos
            await self._cleanup(channel)

    async def _cleanup(self, channel: discord.abc.GuildChannel) -> None:
        """Borra un canal temporal si quedó vacío."""
        if await self.db.fetchone("SELECT 1 FROM vm_channels WHERE channel_id = ?", channel.id) is None:
            return
        if getattr(channel, "members", None):
            return
        await self._unregister(channel.id)
        try:
            await channel.delete(reason="VoiceMaster: canal vacío")
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Tras un reinicio: olvida canales que ya no existen y borra los que quedaron vacíos."""
        for row in await self.db.fetchall("SELECT channel_id FROM vm_channels"):
            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                await self._unregister(row["channel_id"])
            else:
                await self._cleanup(channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.db.execute("DELETE FROM vm_channels WHERE channel_id = ?", channel.id)
        await self.db.execute("DELETE FROM vm_hubs WHERE channel_id = ?", channel.id)

    async def send_interface(self, guild: discord.Guild, channel: discord.TextChannel) -> None:
        if not HAS_V2:
            raise BotError("La interfaz necesita **discord.py 2.6** o superior: `pip install -U discord.py`.")
        thumbnail = guild.icon.with_size(256).url if guild.icon else None
        try:
            await channel.send(view=VoiceInterface(thumbnail=thumbnail))
        except discord.HTTPException as exc:
            if not _is_emoji_error(exc):
                raise
            await channel.send(view=VoiceInterface(thumbnail=thumbnail, safe=True))

    # ------------------------------------------------------------------
    # Comandos: grupo voicemaster (el orden de definición es el orden del help)
    # ------------------------------------------------------------------
    @commands.group(name="voicemaster", aliases=["vm", "vc"], invoke_without_command=True)
    async def voicemaster(self, ctx: Context):
        """Canales de voz temporales (join to create)."""
        await self.bot.get_cog("Help").show(ctx, ctx.command)

    @voicemaster.command(name="setup")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_channels=True, move_members=True)
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def vm_setup(self, ctx: Context):
        """Crea la categoría, el canal de interfaz y el hub «Join to Create»."""
        guild = ctx.guild
        if not HAS_V2:
            raise BotError("VoiceMaster necesita **discord.py 2.6** o superior: `pip install -U discord.py`.")
        existing = await self.db.get_setting(guild.id, "vm_interface")
        if existing and guild.get_channel(existing):
            raise BotError(f"VoiceMaster ya está configurado. Usa `{ctx.clean_prefix}vc reset` para empezar de cero.")
        reason = self._why(ctx.author, "setup")
        category = await guild.create_category("VoiceMaster", reason=reason)
        interface = await guild.create_text_channel(
            "interface",
            category=category,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(
                    send_messages=False, add_reactions=False, create_public_threads=False,
                    create_private_threads=False, send_messages_in_threads=False,
                ),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
            },
            reason=reason,
        )
        hub = await guild.create_voice_channel("Join to Create", category=category, reason=reason)
        await self.db.set_setting(guild.id, "vm_category", category.id)
        await self.db.set_setting(guild.id, "vm_interface", interface.id)
        await self.db.execute("INSERT OR REPLACE INTO vm_hubs (channel_id, guild_id, created) VALUES (?, ?, 1)", hub.id, guild.id)
        await self.send_interface(guild, interface)
        await ctx.approve("La interfaz de **VoiceMaster** se configuró **correctamente**")

    @voicemaster.command(name="add", usage="[canal de voz]")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_channels=True, move_members=True)
    async def vm_add(self, ctx: Context, channel: Optional[discord.VoiceChannel] = None):
        """Añade un hub «join to create»: un canal de voz existente o uno nuevo."""
        guild = ctx.guild
        created = 0
        if channel is None:
            category_id = await self.db.get_setting(guild.id, "vm_category")
            category = guild.get_channel(category_id) if category_id else ctx.channel.category
            channel = await guild.create_voice_channel("Join to Create", category=category, reason=self._why(ctx.author, "add"))
            created = 1
        elif await self.db.fetchone("SELECT 1 FROM vm_hubs WHERE channel_id = ?", channel.id):
            raise BotError(f"{channel.mention} ya es un **hub** de VoiceMaster.")
        await self.db.execute("INSERT OR REPLACE INTO vm_hubs (channel_id, guild_id, created) VALUES (?, ?, ?)", channel.id, guild.id, created)
        await ctx.approve(f"{channel.mention} ahora es un **hub** de VoiceMaster.", emoji=emojis.plus)

    @voicemaster.command(name="hubs")
    @commands.has_permissions(manage_guild=True)
    async def vm_hubs(self, ctx: Context):
        """Lista los hubs «join to create» del servidor."""
        rows = await self.db.fetchall("SELECT channel_id FROM vm_hubs WHERE guild_id = ?", ctx.guild.id)
        channels = [ctx.guild.get_channel(r["channel_id"]) for r in rows]
        lines = [f"{c.mention} · {c.category.name if c.category else 'sin categoría'}" for c in channels if c is not None]
        if not lines:
            raise BotError(f"No hay hubs. Usa `{ctx.clean_prefix}vc setup` o `{ctx.clean_prefix}vc add`.")
        icon = ctx.guild.icon.with_size(256).url if ctx.guild.icon else None
        await paginate_list(ctx, title="Hubs de VoiceMaster", lines=lines, subtitle=[f"**{len(lines)}** hubs"], thumbnail=icon)

    @voicemaster.command(name="removehub", usage="<canal de voz>")
    @commands.has_permissions(manage_guild=True)
    async def vm_removehub(self, ctx: Context, channel: discord.VoiceChannel):
        """Quita un hub (si lo creó el bot, también borra el canal)."""
        row = await self.db.fetchone("SELECT created FROM vm_hubs WHERE channel_id = ? AND guild_id = ?", channel.id, ctx.guild.id)
        if row is None:
            raise BotError(f"{channel.mention} no es un **hub** de VoiceMaster.")
        await self.db.execute("DELETE FROM vm_hubs WHERE channel_id = ?", channel.id)
        if row["created"]:
            await channel.delete(reason=self._why(ctx.author, "removehub"))
        await ctx.approve(f"Se quitó el **hub** **{discord.utils.escape_markdown(channel.name)}** de VoiceMaster.", emoji=emojis.remove)

    @voicemaster.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def vm_reset(self, ctx: Context):
        """Restablece VoiceMaster: borra la interfaz, los hubs creados por el bot y los canales temporales vacíos."""
        guild, reason = ctx.guild, self._why(ctx.author, "reset")
        for row in await self.db.fetchall("SELECT channel_id FROM vm_channels WHERE guild_id = ?", guild.id):
            channel = guild.get_channel(row["channel_id"])
            if channel is not None and not channel.members:
                try:
                    await channel.delete(reason=reason)
                except discord.HTTPException:
                    pass
        await self.db.execute("DELETE FROM vm_channels WHERE guild_id = ?", guild.id)
        for row in await self.db.fetchall("SELECT channel_id, created FROM vm_hubs WHERE guild_id = ?", guild.id):
            channel = guild.get_channel(row["channel_id"])
            if channel is not None and row["created"]:
                try:
                    await channel.delete(reason=reason)
                except discord.HTTPException:
                    pass
        await self.db.execute("DELETE FROM vm_hubs WHERE guild_id = ?", guild.id)
        interface_id = await self.db.get_setting(guild.id, "vm_interface")
        category_id = await self.db.get_setting(guild.id, "vm_category")
        interface = guild.get_channel(interface_id) if interface_id else None
        if interface is not None:
            try:
                await interface.delete(reason=reason)
            except discord.HTTPException:
                pass
        category = guild.get_channel(category_id) if category_id else None
        if category is not None and not category.channels:
            try:
                await category.delete(reason=reason)
            except discord.HTTPException:
                pass
        for key in ("vm_interface", "vm_category", "vm_default_name"):
            await self.db.del_setting(guild.id, key)
        await ctx.approve("La configuración de **VoiceMaster** ha sido **restablecida**")

    @voicemaster.command(name="temporary", aliases=["temp"])
    @commands.has_permissions(manage_guild=True)
    async def vm_temporary(self, ctx: Context):
        """Lista los canales de voz temporales que hay ahora mismo."""
        rows = await self.db.fetchall("SELECT channel_id, owner_id FROM vm_channels WHERE guild_id = ?", ctx.guild.id)
        lines = []
        for row in rows:
            channel = ctx.guild.get_channel(row["channel_id"])
            if channel is not None:
                lines.append(f"{channel.mention} · <@{row['owner_id']}> · {len(channel.members)} dentro")
        if not lines:
            raise BotError("No hay canales temporales activos.")
        await paginate_list(ctx, title="Canales temporales", lines=lines, subtitle=[f"**{len(lines)}** activos"])

    @voicemaster.command(name="sendinterface", aliases=["interface"], usage="[canal]")
    @commands.has_permissions(manage_guild=True)
    async def vm_sendinterface(self, ctx: Context, channel: Optional[discord.TextChannel] = None):
        """Envía (otra vez) la interfaz de botones a un canal de texto."""
        if channel is None:
            interface_id = await self.db.get_setting(ctx.guild.id, "vm_interface")
            channel = (ctx.guild.get_channel(interface_id) if interface_id else None) or ctx.channel
        await self.send_interface(ctx.guild, channel)
        await ctx.approve(f"La interfaz de **VoiceMaster** se envió a {channel.mention}")

    @voicemaster.command(name="default", usage="[plantilla]")
    @commands.has_permissions(manage_guild=True)
    async def vm_default(self, ctx: Context, *, template: Optional[str] = None):
        """Plantilla del nombre de los canales nuevos; `{user}` es el nombre del dueño."""
        if template is None:
            current = await self.db.get_setting(ctx.guild.id, "vm_default_name", DEFAULT_TEMPLATE)
            return await ctx.neutral(f"Los canales nuevos se llaman `{current}`.", title="Plantilla de VoiceMaster")
        template = template.strip()
        if not 1 <= len(template) <= 90:
            raise BotError("La plantilla debe tener entre **1** y **90** caracteres.")
        await self.db.set_setting(ctx.guild.id, "vm_default_name", template)
        await ctx.approve(f"Los canales nuevos se llamarán `{template}`.")

    # ---- comandos del propietario (hacen lo mismo que los botones) ----
    @voicemaster.command(name="lock")
    async def vm_lock(self, ctx: Context):
        """Bloquea tu canal de voz: nadie nuevo puede entrar."""
        await ctx.approve(await self.op_lock(ctx.author))

    @voicemaster.command(name="unlock")
    async def vm_unlock(self, ctx: Context):
        """Desbloquea tu canal de voz."""
        await ctx.approve(await self.op_unlock(ctx.author))

    @voicemaster.command(name="hide", aliases=["ghost"])
    async def vm_hide(self, ctx: Context):
        """Oculta tu canal de voz para los que no están dentro."""
        await ctx.approve(await self.op_hide(ctx.author))

    @voicemaster.command(name="reveal", aliases=["show"])
    async def vm_reveal(self, ctx: Context):
        """Vuelve a mostrar tu canal de voz."""
        await ctx.approve(await self.op_reveal(ctx.author))

    @voicemaster.command(name="claim")
    async def vm_claim(self, ctx: Context):
        """Reclama el canal de voz si su propietario ya no está."""
        await ctx.approve(await self.op_claim(ctx.author))

    @voicemaster.command(name="info")
    async def vm_info(self, ctx: Context):
        """Muestra la información del canal de voz en el que estás."""
        await ctx.send(embed=await self.op_info(ctx.author))

    @voicemaster.command(name="delete", aliases=["destroy"])
    async def vm_delete(self, ctx: Context):
        """Elimina tu canal de voz."""
        await ctx.approve(await self.op_delete(ctx.author))

    @voicemaster.command(name="rename", usage="<nombre>")
    async def vm_rename(self, ctx: Context, *, name: str):
        """Renombra tu canal de voz."""
        await ctx.approve(await self.op_rename(ctx.author, name))

    @voicemaster.command(name="limit", usage="<0-99>")
    async def vm_limit(self, ctx: Context, number: int):
        """Fija el límite de usuarios de tu canal (0 = sin límite)."""
        await ctx.approve(await self.op_limit_set(ctx.author, number))

    @voicemaster.command(name="permit", aliases=["allow"], usage="<miembro>")
    async def vm_permit(self, ctx: Context, member: discord.Member):
        """Da permiso a un miembro para entrar a tu canal (aunque esté bloqueado u oculto)."""
        await ctx.approve(await self.op_permit(ctx.author, member))

    @voicemaster.command(name="reject", aliases=["deny"], usage="<miembro>")
    async def vm_reject(self, ctx: Context, member: discord.Member):
        """Rechaza a un miembro: le prohíbe entrar y lo saca si está dentro."""
        await ctx.approve(await self.op_reject(ctx.author, member))

    @voicemaster.command(name="bitrate", usage="<kbps>")
    async def vm_bitrate(self, ctx: Context, kbps: int):
        """Cambia el bitrate de tu canal (en kbps)."""
        await ctx.approve(await self.op_bitrate(ctx.author, kbps))

    @voicemaster.command(name="region", usage="<región | auto>")
    async def vm_region(self, ctx: Context, region: str):
        """Cambia la región de voz de tu canal."""
        await ctx.approve(await self.op_region(ctx.author, region))

    @voicemaster.command(name="drag", aliases=["pull"], usage="<miembro>")
    @commands.bot_has_permissions(move_members=True)
    async def vm_drag(self, ctx: Context, member: discord.Member):
        """Trae a tu canal a un miembro que está en otro canal de voz."""
        await ctx.approve(await self.op_drag(ctx.author, member))


async def setup(bot) -> None:
    await bot.add_cog(VoiceMaster(bot))
