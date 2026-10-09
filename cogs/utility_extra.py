"""Paquete de utilidades original para Toui."""
from __future__ import annotations
import base64, datetime as dt, html, ipaddress, json, math, random, re, statistics, string, unicodedata, urllib.parse, uuid, textwrap
from collections import Counter
import discord
from discord.ext import commands
from config import Colors
from core.cog import BaseCog

GROUPS = [["Texto",["uppercase","lowercase","titlecase","capitalize","swapcase","reverse-text","sort-words","unique-words","remove-spaces","remove-linebreaks"]],["Análisis",["text-length","word-count","line-count","vowel-count","consonant-count","digit-count","space-count","punctuation-count","initials","reverse-words"]],["Codificación",["base64-encode","base64-decode","url-encode","url-decode","hex-encode","hex-decode","binary-encode","binary-decode","rot13","unicode-codes"]],["Formato",["markdown-bold","markdown-italic","markdown-underline","markdown-strike","markdown-spoiler","markdown-quote","markdown-code","markdown-bullet","markdown-numbered","markdown-inline"]],["Validación",["check-email","check-url","check-ipv4","check-hex","check-number","check-integer","check-json","check-binary","check-base64","check-morse"]],["Matemáticas",["percent-of","percent-change","average","median","range-size","factorial","square","cube","square-root","hypotenuse"]],["Conversión",["km-to-miles","miles-to-km","cm-to-inches","inches-to-cm","kg-to-lbs","lbs-to-kg","c-to-f","f-to-c","kmh-to-mph","mph-to-kmh"]],["Aleatorio",["random-number","random-choice","shuffle-list","pick-one","coin","dice","random-color","random-hex","random-uuid","yes-or-no"]],["Listas",["list-number","list-sort","list-reverse","list-dedupe","list-count","list-first","list-last","list-join","list-split","list-random"]],["Fecha",["unix-now","iso-now","utc-now","date-today","year-now","month-now","weekday-now","days-until","minutes-to-hours","seconds-to-hours"]],["Texto avanzado",["slugify","strip-accents","remove-punctuation","remove-numbers","keep-numbers","keep-letters","trim-text","collapse-spaces","repeat-text","wrap-text"]],["Colores",["color-hex","color-rgb","color-invert","color-brightness","color-contrast","color-random-rgb","color-random-hsl","color-hex-rgb","color-rgb-hex","color-preview"]],["Nombres",["make-acronym","word-initials","camel-case","snake-case","kebab-case","pascal-case","constant-case","alternate-case","sentence-case","word-frequency"]],["Extra",["countdown-seconds","format-bytes","format-duration","ordinal-number","roman-number","roman-decode","morse-encode","morse-decode","html-escape","html-unescape"]]]

def nums(s): return [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", s)]
def number(s):
    n=nums(s)
    if not n or not math.isfinite(n[0]): raise ValueError("Escribe un número válido.")
    return n[0]

def calculate(a,s):
    t=s.strip(); w=t.split(); now=dt.datetime.now(dt.timezone.utc)
    if a=="uppercase": return t.upper()
    if a=="lowercase": return t.lower()
    if a=="titlecase": return t.title()
    if a=="capitalize": return t.capitalize()
    if a=="swapcase": return t.swapcase()
    if a=="reverse-text": return t[::-1]
    if a=="sort-words": return " ".join(sorted(w,key=str.casefold))
    if a=="unique-words": return " ".join(dict.fromkeys(w))
    if a=="remove-spaces": return re.sub(r"\s+","",t)
    if a=="remove-linebreaks": return re.sub(r"[\r\n]+"," ",t)
    if a=="text-length": return f"Caracteres: {len(t)}"
    if a=="word-count": return f"Palabras: {len(w)}"
    if a=="line-count": return f"Líneas: {len(t.splitlines()) if t else 0}"
    if a=="vowel-count": return f"Vocales: {sum(c.lower() in 'aeiouáéíóúü' for c in t)}"
    if a=="consonant-count": return f"Consonantes: {sum(c.isalpha() and c.lower() not in 'aeiouáéíóúü' for c in t)}"
    if a=="digit-count": return f"Dígitos: {sum(c.isdigit() for c in t)}"
    if a=="space-count": return f"Espacios: {sum(c.isspace() for c in t)}"
    if a=="punctuation-count": return f"Puntuación: {sum(unicodedata.category(c).startswith('P') for c in t)}"
    if a in ("initials","make-acronym"): return "".join(x[0].upper() for x in w if x)
    if a=="reverse-words": return " ".join(w[::-1])
    if a=="base64-encode": return base64.b64encode(t.encode()).decode()
    if a=="base64-decode":
        try: return base64.b64decode(t,validate=True).decode()
        except Exception as e: raise ValueError("Base64 UTF-8 inválido.") from e
    if a=="url-encode": return urllib.parse.quote(t,safe="")
    if a=="url-decode": return urllib.parse.unquote(t)
    if a=="hex-encode": return t.encode().hex()
    if a=="hex-decode":
        try: return bytes.fromhex(t).decode()
        except Exception as e: raise ValueError("Hexadecimal UTF-8 inválido.") from e
    if a=="binary-encode": return " ".join(f"{b:08b}" for b in t.encode())
    if a=="binary-decode":
        try: return bytes(int(x,2) for x in t.split()).decode()
        except Exception as e: raise ValueError("Binario inválido; usa bytes de 8 bits separados por espacios.") from e
    if a=="rot13": return t.translate(str.maketrans(string.ascii_letters,string.ascii_lowercase[13:]+string.ascii_lowercase[:13]+string.ascii_uppercase[13:]+string.ascii_uppercase[:13]))
    if a=="unicode-codes": return " ".join(f"U+{ord(c):04X}" for c in t[:100])
    if a=="markdown-bold": return "**"+t+"**"
    if a=="markdown-italic": return "*"+t+"*"
    if a=="markdown-underline": return "__"+t+"__"
    if a=="markdown-strike": return "~~"+t+"~~"
    if a=="markdown-spoiler": return "||"+t+"||"
    if a=="markdown-quote": return "\n".join("> "+x for x in (t.splitlines() or [""]))
    if a=="markdown-code": return "~~~\n"+t[:1700]+"\n~~~"
    if a=="markdown-bullet": return "\n".join("• "+x for x in (t.splitlines() or [""]))
    if a=="markdown-numbered": return "\n".join(f"{i}. {x}" for i,x in enumerate(t.splitlines(),1))
    if a=="markdown-inline": return "\"" + t.replace("\"", "’") + "\""
    if a=="check-email": return "Formato válido." if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",t) else "Correo inválido."
    if a=="check-url":
        u=urllib.parse.urlparse(t); return "URL http(s) válida." if u.scheme in ("http","https") and u.netloc else "Escribe URL completa con https://."
    if a=="check-ipv4":
        try: return f"IPv4 válida: {ipaddress.IPv4Address(t)}"
        except Exception: return "IPv4 inválida."
    if a=="check-hex": return "HEX válido." if re.fullmatch(r"#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})",t) else "HEX inválido."
    if a=="check-number":
        try: number(t); return "Número válido."
        except ValueError: return "Número inválido."
    if a=="check-integer":
        try: return "Entero válido." if float(t).is_integer() else "No es entero."
        except Exception: return "Entero inválido."
    if a=="check-json":
        try: return "JSON válido: "+type(json.loads(t)).__name__
        except Exception as e: return "JSON inválido: "+str(e)[:100]
    if a=="check-binary": return "Binario válido." if re.fullmatch(r"[01\s]+",t) else "Binario inválido."
    if a=="check-base64":
        try: base64.b64decode(t,validate=True); return "Base64 válido."
        except Exception: return "Base64 inválido."
    if a=="check-morse": return "Alfabeto Morse válido." if re.fullmatch(r"[.\-/\s]+",t) else "Morse inválido."
    if a=="percent-of":
        n=nums(t)
        if len(n)<2: raise ValueError("Formato: porcentaje, cantidad. Ejemplo: 15, 200")
        return f"{n[0]}% de {n[1]} = {n[0]*n[1]/100:g}"
    if a=="percent-change":
        n=nums(t)
        if len(n)<2 or n[0]==0: raise ValueError("Formato: valor anterior, valor nuevo; el anterior no puede ser 0.")
        return f"Cambio: {(n[1]-n[0])/abs(n[0])*100:+.2f}%"
    if a in ("average","median","range-size"):
        n=nums(t)
        if not n: raise ValueError("Escribe números separados por comas.")
        f={"average":statistics.mean,"median":statistics.median,"range-size":lambda z:max(z)-min(z)}[a]
        return f"Resultado: {f(n):g}"
    if a=="factorial":
        n=int(number(t))
        if n<0 or n>500: raise ValueError("Usa un entero entre 0 y 500.")
        return str(math.factorial(n))
    if a=="square": return f"{number(t)**2:g}"
    if a=="cube": return f"{number(t)**3:g}"
    if a=="square-root":
        n=number(t)
        if n<0: raise ValueError("La raíz real requiere un número no negativo.")
        return f"{math.sqrt(n):g}"
    if a=="hypotenuse":
        n=nums(t)
        if len(n)<2: raise ValueError("Formato: cateto A, cateto B.")
        return f"Hipotenusa: {math.hypot(n[0],n[1]):g}"
    conv={"km-to-miles":(.621371,"mi"),"miles-to-km":(1.609344,"km"),"cm-to-inches":(1/2.54,"in"),"inches-to-cm":(2.54,"cm"),"kg-to-lbs":(2.20462262,"lb"),"lbs-to-kg":(1/2.20462262,"kg"),"kmh-to-mph":(.621371,"mph"),"mph-to-kmh":(1.609344,"km/h")}
    if a in conv:
        f,u=conv[a]; n=number(t); return f"{n:g} = {n*f:g} {u}"
    if a=="c-to-f": return f"{number(t):g} °C = {number(t)*9/5+32:g} °F"
    if a=="f-to-c": return f"{number(t):g} °F = {(number(t)-32)*5/9:g} °C"
    if a=="random-number":
        n=[int(x) for x in re.findall(r"-?\d+",t)]; lo,hi=(n[0],n[1]) if len(n)>1 else (1,100)
        if lo>hi: lo,hi=hi,lo
        return str(random.randint(lo,hi))
    if a in ("random-choice","pick-one","shuffle-list","list-number","list-sort","list-reverse","list-dedupe","list-count","list-first","list-last","list-join","list-split","list-random"):
        items=[x.strip() for x in re.split(r"[,;|]",t) if x.strip()]
        if a=="list-count": return f"Elementos: {len(items)}"
        if not items: raise ValueError("Escribe elementos separados por comas.")
        if a in ("random-choice","pick-one","list-random"): return random.choice(items)
        if a=="shuffle-list": random.shuffle(items); return ", ".join(items)
        if a=="list-number": return "\n".join(f"{i}. {x}" for i,x in enumerate(items,1))
        if a=="list-sort": return ", ".join(sorted(items,key=str.casefold))
        if a=="list-reverse": return ", ".join(items[::-1])
        if a=="list-dedupe": return ", ".join(dict.fromkeys(items))
        if a=="list-first": return items[0]
        if a=="list-last": return items[-1]
        if a=="list-join": return " · ".join(items)
        return "\n".join(items)
    if a=="coin": return random.choice(["Cara","Cruz"])
    if a=="dice": return f"Dado: {random.randint(1,6)}"
    if a in ("random-color","random-hex"): return f"#{random.randint(0,0xFFFFFF):06X}"
    if a=="random-uuid": return str(uuid.uuid4())
    if a=="yes-or-no": return random.choice(["Sí","No","Tal vez","No lo sé"])
    if a=="unix-now": return str(int(now.timestamp()))
    if a=="iso-now": return now.isoformat(timespec="seconds")
    if a=="utc-now": return now.strftime("%Y-%m-%d %H:%M:%S UTC")
    if a=="date-today": return now.strftime("%Y-%m-%d UTC")
    if a=="year-now": return str(now.year)
    if a=="month-now": return str(now.month)
    if a=="weekday-now": return str(now.weekday()+1)
    if a=="days-until":
        try: return f"Días desde hoy hasta la fecha: {(dt.date.fromisoformat(t)-now.date()).days}"
        except Exception as e: raise ValueError("Formato requerido: AAAA-MM-DD.") from e
    if a=="minutes-to-hours": return f"{number(t):g} minutos = {number(t)/60:g} horas"
    if a=="seconds-to-hours": return f"{number(t):g} segundos = {number(t)/3600:g} horas"
    if a=="slugify":
        z="".join(c for c in unicodedata.normalize("NFKD",t) if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9]+","-",z.lower()).strip("-")
    if a=="strip-accents": return "".join(c for c in unicodedata.normalize("NFKD",t) if not unicodedata.combining(c))
    if a=="remove-punctuation": return "".join(c for c in t if not unicodedata.category(c).startswith("P"))
    if a=="remove-numbers": return re.sub(r"\d+","",t)
    if a=="keep-numbers": return "".join(c for c in t if c.isdigit())
    if a=="keep-letters": return "".join(c for c in t if c.isalpha() or c.isspace())
    if a=="trim-text": return t.strip()
    if a=="collapse-spaces": return re.sub(r"\s+"," ",t).strip()
    if a=="repeat-text":
        p=t.split("|",1); n=int(p[1]) if len(p)>1 and p[1].strip().isdigit() else 2
        if not 1<=n<=10: raise ValueError("Usa entre 1 y 10 repeticiones.")
        return "\n".join([p[0].strip()]*n)
    if a=="wrap-text":
        p=t.split("|",1); width=int(p[1]) if len(p)>1 and p[1].strip().isdigit() else 40
        if not 10<=width<=150: raise ValueError("El ancho debe estar entre 10 y 150.")
        return textwrap.fill(p[0],width)
    if a in ("color-hex","color-rgb","color-invert","color-brightness","color-contrast","color-hex-rgb","color-preview"):
        h=t.lstrip("#")
        if not re.fullmatch(r"[0-9a-fA-F]{6}",h): raise ValueError("Usa HEX de 6 dígitos, por ejemplo FF8800.")
        rgb=[int(h[i:i+2],16) for i in (0,2,4)]
        if a=="color-hex": return "#"+h.upper()
        if a in ("color-rgb","color-hex-rgb"): return f"RGB({rgb[0]}, {rgb[1]}, {rgb[2]})"
        if a=="color-invert": return "#"+ "".join(f"{255-x:02X}" for x in rgb)
        if a=="color-brightness": return f"Brillo aproximado: {(0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2])/255:.3f}"
        if a=="color-contrast": return "Texto recomendado: negro" if sum(rgb)>382 else "Texto recomendado: blanco"
        return f"Color #{h.upper()} · RGB({rgb[0]}, {rgb[1]}, {rgb[2]})"
    if a=="color-random-rgb": return "RGB("+", ".join(str(random.randint(0,255)) for _ in range(3))+")"
    if a=="color-random-hsl": return f"HSL({random.randint(0,359)}, {random.randint(20,100)}%, {random.randint(20,80)}%)"
    if a=="color-rgb-hex":
        n=[int(x) for x in re.findall(r"\d+",t)]
        if len(n)<3 or any(x>255 for x in n[:3]): raise ValueError("Formato: 255, 136, 0.")
        return "#"+"".join(f"{x:02X}" for x in n[:3])
    if a=="word-initials": return " ".join(x[0].upper()+"." for x in w if x)
    if a in ("camel-case","pascal-case","snake-case","kebab-case","constant-case"):
        bits=re.findall(r"[A-Za-z0-9]+",t.lower())
        if a=="snake-case": return "_".join(bits)
        if a=="kebab-case": return "-".join(bits)
        if a=="constant-case": return "_".join(bits).upper()
        z="".join(x.title() for x in bits)
        return z if a=="pascal-case" else z[:1].lower()+z[1:]
    if a=="alternate-case": return "".join(c.upper() if i%2 else c.lower() for i,c in enumerate(t))
    if a=="sentence-case": return t[:1].upper()+t[1:].lower()
    if a=="word-frequency": return "\n".join(f"{k}: {v}" for k,v in Counter(x.lower() for x in w).most_common(25))
    if a=="countdown-seconds":
        n=int(number(t))
        if not 0<=n<=86400: raise ValueError("Usa un número entre 0 y 86400.")
        return f"{n//3600:02d}:{(n%3600)//60:02d}:{n%60:02d}"
    if a=="format-bytes":
        n=number(t)
        if n<0: raise ValueError("Los bytes no pueden ser negativos.")
        units=["B","KB","MB","GB","TB"]; i=0
        while n>=1024 and i<len(units)-1: n/=1024; i+=1
        return f"{n:.2f} {units[i]}"
    if a=="format-duration":
        n=int(number(t))
        if n<0: raise ValueError("La duración no puede ser negativa.")
        return f"{n//86400}d {(n%86400)//3600}h {(n%3600)//60}m {n%60}s"
    if a=="ordinal-number": return f"{int(number(t))}.º"
    if a=="roman-number":
        n=int(number(t))
        if not 1<=n<=3999: raise ValueError("Usa un entero entre 1 y 3999.")
        pairs=((1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")); out=""
        for v,sym in pairs:
            while n>=v: out+=sym; n-=v
        return out
    if a=="roman-decode":
        vals={"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}; z=t.upper()
        if not z or any(c not in vals for c in z): raise ValueError("Escribe un número romano válido.")
        return str(sum(-vals[c] if i+1<len(z) and vals[c]<vals[z[i+1]] else vals[c] for i,c in enumerate(z)))
    if a=="morse-encode":
        m=dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",[".-","-...","-.-.","-..",".","..-.","--.","....","..",".---","-.-",".-..","--","-.","---",".--.","--.-",".-.","...","-","..-","...-",".--","-..-","-.--","--..","-----",".----","..---","...--","....-",".....","-....","--...","---..","----."])); m[" "]="/"
        return " ".join(m[c.upper()] for c in t if c.upper() in m)
    if a=="morse-decode":
        m=dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",[".-","-...","-.-.","-..",".","..-.","--.","....","..",".---","-.-",".-..","--","-.","---",".--.","--.-",".-.","...","-","..-","...-",".--","-..-","-.--","--..","-----",".----","..---","...--","....-",".....","-....","--...","---..","----."])); m[" "]="/"
        rev={v:k for k,v in m.items()}
        try: return "".join(rev[x] if x!="/" else " " for x in t.split())
        except KeyError as e: raise ValueError("Código Morse inválido.") from e
    if a=="html-escape": return html.escape(t)
    if a=="html-unescape": return html.unescape(t)
    raise ValueError("Operación no disponible.")

class UtilityExtra(BaseCog):
    category="Utilidad"
    guild_only=False
    def __init__(self,bot):
        super().__init__(bot)
        existing=set(bot.all_commands)
        for category,names in GROUPS:
            for name in names:
                if name in existing: continue
                callback=self._make_callback(name,category)
                self.__cog_commands__ = (*self.__cog_commands__, commands.Command(callback, name=name, help=f"Herramienta de {category.lower()}.", usage="[valor]"))
                existing.add(name)
    @staticmethod
    def _make_callback(action,category):
        async def callback(self,ctx,*,value:str=""):
            try: output=str(calculate(action,value))
            except (ValueError,OverflowError,ZeroDivisionError) as exc: output=str(exc) or "No pude procesar ese valor."
            output=output or "(resultado vacío)"
            if len(output)>1800: output=output[:1790]+"…"
            embed=discord.Embed(description=output,color=Colors.DEFAULT)
            embed.set_author(name=f"{action} · Toui")
            embed.set_footer(text=f"Utilidad · {category}")
            await ctx.send(embed=embed)
        callback.__name__="cmd_"+action.replace("-","_")
        callback.__doc__=f"Herramienta de {category.lower()}"
        return callback

async def setup(bot): await bot.add_cog(UtilityExtra(bot))
