# Bot multipropósito (discord.py)

Bot de comandos con prefijo `,` (cambiable), embeds de una línea (emoji + mención + mensaje) al estilo
Greed, help paginado, emojis configurables y base de datos SQLite. Pensado para crecer por tandas hasta ~400 comandos.

## Arrancar

1. Python 3.10 o superior.
2. `pip install -r requirements.txt`
3. Copia `.env.example` a `.env` y pega el token de tu bot (`DISCORD_TOKEN`). Pon tu ID en `OWNER_IDS`.
4. En el [Discord Developer Portal](https://discord.com/developers/applications) → tu app → **Bot**,
   activa **Server Members Intent** y **Message Content Intent**.
5. Invita el bot con el scope `bot` y los permisos que necesite (para empezar, Administrador).
   Su rol debe estar **por encima** de los roles que quiera moderar.
6. `python main.py`

`python check.py` carga todos los cogs sin conectarse a Discord y te dice cuántos comandos llevas
por categoría. Úsalo cada vez que agregues una tanda.

## Estructura

```
main.py            arranque
config.py          prefijo, dueños y COLORES de los embeds
core/
  embeds.py        estilo de los embeds (éxito / error / aviso)
  emojis.py        mapa de emojis (se sobrescribe con emojis.json)
  context.py       ctx.approve / ctx.deny / ctx.warn / ctx.neutral
  db.py            SQLite async + ajustes por servidor (get_setting / set_setting)
  cases.py         casos de moderación, modlog y DM al sancionado
  checks.py        jerarquía de roles (nadie sanciona a quien no debe)
  converters.py    Duration: "30m", "2h", "1d12h", "1w"
  views.py         paginador con botones (◀ ▶ 🔍 🚫) y confirmaciones
  quote_image.py   imagen del comando quote (Pillow)
assets/fonts/      fuentes OFL del comando quote
cogs/              cada archivo es un módulo; se cargan solos
```

## Añadir comandos

Crea un archivo en `cogs/` y se carga automáticamente:

```python
from discord.ext import commands
from core.cog import BaseCog
from core.context import Context


class Utility(BaseCog):
    category = "Utilidad"   # categoría que se ve en help
    guild_only = False      # True (por defecto) = solo en servidores

    @commands.command(name="ping", usage="")
    async def ping(self, ctx: Context):
        """Muestra la latencia del bot."""          # <- esto es la descripción en help
        await ctx.approve(f"Pong · **{round(ctx.bot.latency * 1000)}ms**")


async def setup(bot):
    await bot.add_cog(Utility(bot))
```

Reglas del proyecto:

- Errores para el usuario: `raise BotError("mensaje")` sale como aviso ámbar (⚠, errores de uso);
  `raise BotError("mensaje", kind="error")` sale en rojo (✖, "la acción falló").
- Parámetros y permisos en `código` y palabras clave en **negrita** dentro de los mensajes (como Greed).
- En un grupo sin subcomando, muestra su ayuda con `await self.bot.get_cog("Help").show(ctx, ctx.command)`.
- Para que el help muestre un ejemplo propio: `@commands.command(extras={"example": "ban @usuario spam"})`.
- Jerarquía antes de sancionar: `checks.ensure_hierarchy(ctx, member, "banear")`.
- Ajustes por servidor: `await self.bot.db.get_setting(guild_id, "clave", default)`.
- Nunca escribas emojis sueltos: `from core.emojis import emojis` y usa `emojis.ban`, `emojis.success`...
- Varios cogs pueden compartir `category` (Moderación ya usa tres archivos).

## Tus emojis

Tus 9 emojis ya vienen configurados en `core/emojis.py` (success, error, warn, plus, remove, prev, next,
search y close). Para que Discord los muestre, el bot tiene que estar en el servidor que los aloja
(o súbelos como "Application Emojis" en el Developer Portal y cambia los IDs).

Para cambiar uno sin reiniciar (solo dueños), acepta el emoji, su ID o la URL del CDN:
`,botemoji set success 1556558143117459476`
`,botemoji list` muestra todos los nombres disponibles y `,botemoji check` dice cuáles de tus emojis puede usar el bot.
Si un emoji no es accesible (el bot no está en su servidor o fue borrado), los botones usan un emoji normal
en su lugar en vez de fallar. También puedes copiar `emojis.example.json`
a `emojis.json` y editarlo a mano.

## VoiceMaster

`,vc setup` crea la categoría **VoiceMaster** con el canal `#interface` (la interfaz de botones) y el hub
**Join to Create**. Quien entra al hub recibe su propio canal de voz y es su propietario; cuando queda vacío se
borra. Los 10 botones de la interfaz siguen funcionando después de reiniciar el bot.

- Botones: bloquear, desbloquear, ocultar (ghost), revelar, reclamar (si el dueño ya no está), información,
  aumentar y reducir el límite de usuarios (con formulario), renombrar (con formulario) y eliminar.
- Las respuestas de los botones son privadas (solo las ve quien pulsó) y llevan la barra arena.
- Todo lo de los botones también existe como subcomando: `,vc lock`, `,vc rename <nombre>`, `,vc limit <n>`,
  `,vc permit/reject <miembro>`, `,vc bitrate`, `,vc region`, `,vc drag`...
- Administración (necesita Gestionar servidor): `setup`, `add`, `hubs`, `removehub`, `reset`, `temporary`,
  `sendinterface` y `default` (plantilla del nombre, `{user}` = dueño; por defecto `Canal de {user}`).
- El bot necesita los permisos Gestionar canales y Mover miembros. La interfaz requiere discord.py 2.6 o superior.

## Alias

Cada servidor puede crear atajos para cualquier comando (necesita Gestionar servidor):
`,alias add un unban`, `,alias remove un`, `,alias list`, `,alias removeall unban`, `,alias reset`.
Un alias nunca puede pisar un comando real ni un alias integrado (las letras sueltas `b`, `k`, `m`, `s`, `a`, `r`,
`q`, `l`, `j`, `p`, `i`, `g`... ya son alias integrados). También sirven para subcomandos: `,alias add dar role add`.

## Estilo de los embeds

Copiado de las capturas de Greed:

- Respuestas de una línea: `emoji @autor: mensaje`. Barra verde `#9FE878` (éxito), ámbar `#F89E18`
  (aviso o error de uso) y roja `#F86060` (fallo). Colores en `config.py` → `Colors`
  (también arena `#A3947B` para snipe y serverinfo, y gris `#84807E` para avatar y userinfo).
- Embeds informativos (userinfo, serverinfo, snipe): autor arriba, miniatura, campos en cita `> ...` y pie
  con ID; el snipe lleva tu avatar en el pie.
- Listas numeradas (`roles`): contenedor con barra arena, título + miniatura, separadores, líneas `01 @rol · ID`,
  pie `Página 1/4` y botones dentro del mismo cuadro. Usa `paginate_list()` de `core/views.py` para crear más
  listas así. Necesita discord.py 2.6 o superior (`pip install -U discord.py`); con una versión anterior cae a
  embeds normales.
- `quote` genera una imagen con tres menús (fuente, tema, diseño); añade fuentes en `assets/fonts/`.
- Help por comando: autor, título, descripción en cita, campos Aliases / Parameters / Information,
  bloque Usage (Syntax + Example), pie `Página 1/23 (23 entradas) • Módulo: ...` y botones ◀ ▶ 🔍 🚫.
- El fondo negro del embed y su borde los pinta tu tema de Discord, no el bot.

El formato de las respuestas vive en `core/embeds.py`; el del help, en `cogs/help.py`.

## Notas

- Los comandos son de **prefijo** (como Bleed/Greed). Discord limita los slash commands a 100,
  así que con 400 comandos no cabrían.
- Los mensajes del bot están en español (son texto normal dentro de cada comando).
- Si lo subes a un hosting con disco efímero, monta un volumen en `data/` o perderás los casos
  y ajustes en cada despliegue.

## Progreso

| Categoría   | Objetivo | Hecho |
|-------------|---------:|------:|
| Moderación  | 60       | 63    |
| Utilidad    | 70       | 67    |
| Servidor    | 60       | 9     |
| Voicemaster | 25       | 23    |
| Setup       | 40       | 0     |
| Logs        | 25       | 0     |
| Seguridad   | 40       | 0     |
| Extras      | 80       | 0     |
