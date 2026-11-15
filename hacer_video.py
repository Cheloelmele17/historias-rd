#!/usr/bin/env python3
# Video de datos curiosos EN INGLÉS (público de EE. UU.) con estilo "menta y noche", basado SOLO en Wikipedia.
#   tema y datos -> Wikipedia en inglés (la IA solo explica lo que dice el artículo)
#   guion        -> Groq (clave GROQ_API_KEY) o Gemini (GEMINI_API_KEY), con verificación contra el artículo
#   fotos        -> fotos reales de Wikimedia Commons
#   voz          -> edge-tts
#   video        -> Pillow + ffmpeg, 1080x1920
# Resultado: salida/video.mp4, salida/portada.jpg, salida/descripcion.txt, salida/guion.txt
# Prueba sin internet: python3 hacer_video.py --prueba-local
import asyncio, datetime, io, json, os, pathlib, random, re, subprocess, sys, time
import urllib.error, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# ===== Ajustes de marca (cambiar aquí) =====
USUARIO = os.environ.get("USUARIO_TIKTOK", "")        # ej. "@datodiario" (vacío = no se muestra)
MENTA = (46, 242, 194)                                   # #2EF2C2
NOCHE = (20, 17, 43)                                     # #14112B
SERIE = "FACT"
# ===========================================

RAIZ = pathlib.Path(__file__).resolve().parent
SAL = RAIZ / "salida"
TMP = SAL / "tmp"
W, H, FPS = 1080, 1920, 30
S = W / 720                     # escala del diseño (se diseñó en 720x1280)
PORTADA_SEG, CIERRE_SEG = 1.3, 2.2
VOCES = [os.environ.get("VOZ", "en-US-AndrewNeural"), "en-US-ChristopherNeural", "en-US-GuyNeural"]
UA = "DatoDiarioBot/1.0 (https://github.com/Cheloelmele17/historias-rd)"
# Temas que mejor pagan en publicidad: tecnología, dinero, empresas, ciencia
CATEGORIAS = ["TECHNOLOGY", "MONEY HISTORY", "FAMOUS COMPANIES", "SPACE", "INVENTIONS", "ECONOMICS",
              "SCIENCE", "ENGINEERING", "HUMAN BODY", "BUSINESS LEGENDS"]
PRUEBA = "--prueba-local" in sys.argv


def s(v):
    return int(round(v * S))


def hexass(rgb):
    return "&H%02X%02X%02X&" % (rgb[2], rgb[1], rgb[0])


def fuente(tam):
    for f in [RAIZ / "fuentes" / "Poppins-ExtraBold.ttf", RAIZ / "fuentes" / "Poppins-Bold.ttf",
              pathlib.Path("/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"),
              pathlib.Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")]:
        if f.exists():
            return ImageFont.truetype(str(f), tam)
    return ImageFont.load_default(tam)


def nombre_fuente():
    return "Poppins ExtraBold" if (RAIZ / "fuentes" / "Poppins-ExtraBold.ttf").exists() else "Poppins"


def correr(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd)[:300], flush=True)
    subprocess.run(cmd, check=True, **kw)


def duracion(ruta):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def bajar(url, headers=None, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code}: {e.read()[:200]!r}")


def bajar_json(url, **kw):
    return json.loads(bajar(url, **kw).decode("utf-8", "replace"))


# ---------- 1. Registro ----------
def registro():
    reg = RAIZ / "registro.txt"
    if not reg.exists():
        return []
    return [l for l in reg.read_text(encoding="utf-8").splitlines() if l.count("|") >= 3 and not l.startswith("#")]


# ---------- 2. IA (Groq o Gemini) ----------
def proveedores():
    clave = os.environ.get("GROQ_API_KEY", "").strip()
    if clave:
        try:
            ids = [m["id"] for m in bajar_json("https://api.groq.com/openai/v1/models",
                                               headers={"Authorization": f"Bearer {clave}"})["data"]]
        except Exception as e:
            print(f"  no se pudo leer la lista de modelos de Groq: {e}")
            ids = []
        preferidos = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct",
                      "meta-llama/llama-4-maverick-17b-128e-instruct", "qwen/qwen3-32b"]
        elegidos = [m for m in preferidos if m in ids]
        elegidos += [m for m in ids if m not in elegidos and any(k in m for k in ("gpt-oss", "llama-3", "llama-4", "qwen", "kimi"))
                     and not any(k in m for k in ("guard", "whisper", "tts", "prompt"))]
        for m in (elegidos or preferidos[:2])[:4]:
            yield (f"groq:{m}", "https://api.groq.com/openai/v1/chat/completions", m, clave)
    clave = os.environ.get("GEMINI_API_KEY", "").strip()
    if clave:
        for m in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
            yield (f"gemini:{m}", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", m, clave)


def preguntar(sistema, usuario, temperatura=0.7):
    ultimo = None
    for intento in range(4):
        for nombre, url, modelo, clave in proveedores():
            cuerpo = {"model": modelo, "temperature": temperatura,
                      "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]}
            if intento % 2 == 0:  # a veces el modo JSON estricto falla; en los reintentos se pide sin él
                cuerpo["response_format"] = {"type": "json_object"}
            try:
                r = bajar_json(url, headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"},
                               data=json.dumps(cuerpo).encode(), timeout=180)
                texto = r["choices"][0]["message"]["content"]
                return json.loads(re.search(r"\{.*\}", texto, re.S).group(0)), nombre
            except Exception as e:
                ultimo = e
                print(f"  {nombre} falló: {str(e)[:300]}", flush=True)
                time.sleep(65 if "429" in str(e) else 5)  # el plan gratis limita el texto por minuto
    raise SystemExit(f"Ninguna IA respondió (¿falta GROQ_API_KEY?): {ultimo}")


# ---------- 3. Tema real de Wikipedia ----------
def wiki_articulo(titulo):
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts|info", "explaintext": 1, "redirects": 1,
                                "inprop": "url", "titles": titulo, "format": "json", "formatversion": 2})
    p = bajar_json(f"https://en.wikipedia.org/w/api.php?{q}")["query"]["pages"][0]
    if p.get("missing") or not p.get("extract"):
        return None
    texto = re.split(r"\n== (See also|References|Notes|Further reading|External links|Bibliography|Sources|Citations) ==", p["extract"])[0]
    return {"titulo": p["title"], "url": p.get("fullurl", ""), "texto": texto.strip()}


def escoger_tema(categoria, usados):
    sistema = ("You are the editor of a short-video channel of surprising facts for a US audience. You propose English "
               "Wikipedia articles full of surprising, verifiable facts. Reply only with JSON.")
    lista = ", ".join(usados[-120:]) or "none"
    usuario = (f"Category: {categoria}. Give me 8 EXACT titles of existing articles on en.wikipedia.org "
               f"(CONCRETE, specific topics: one invention, one company, one coin or banknote, one market crash, one machine, one spacecraft, "
               f"one discovery; NOT whole countries or broad topics, no living people, no politics, nothing about what to invest in). "
               f"Do not use any of these: {lista}.\n"
               '{"titulos": ["...", "..."]}')
    propuesta, _ = preguntar(sistema, usuario, temperatura=1.0)
    lista_t = propuesta.get("titulos") or next((v for v in propuesta.values() if isinstance(v, list)), [])
    titulos = [t for t in lista_t if isinstance(t, str)]
    print(f"  propuestas: {titulos}", flush=True)
    random.shuffle(titulos)
    for t in titulos:
        try:
            art = wiki_articulo(t)
        except Exception as e:
            print(f"  Wikipedia falló con {t}: {e}")
            continue
        if not art or art["titulo"] in usados or len(art["texto"]) < 2500:
            continue
        fotos = fotos_commons(art["titulo"], solo_contar=True)
        if fotos < 4:
            print(f"  {art['titulo']}: pocas fotos ({fotos})")
            continue
        print(f"Tema: {art['titulo']} ({len(art['texto'])} letras, {fotos} fotos)")
        return art
    raise SystemExit("No se encontró un artículo bueno en Wikipedia para hoy")


# ---------- 4. Guion basado en el artículo ----------
SISTEMA_GUION = """You write scripts for a TikTok/Facebook Reels channel of surprising facts for an American audience.
I give you the text of a Wikipedia article. Write the script USING ONLY information that is in that text.
Never add facts, numbers, records, comparisons or places that are not in the article. Do not mix in other topics.
Pick the most surprising things in the article. Every sentence must be something the article literally says; no filler claims, no exaggeration.
NARRATION: 170 to 195 words (a bit over one minute). Tell it like you would tell a friend: talk to "you", sentences of 15 words max,
rhetorical questions and natural spoken expressions ("picture this", "here's the crazy part", "and it gets weirder"). Casual American English.
No Latin scientific names, no long lists; choose the most impressive facts and explain why they matter.
Copy every number, name and date EXACTLY as the article writes it, in digits (e.g. "Boeing 747", "1998", "28,000"). Never convert, estimate or invent comparisons.
No investment or financial advice, only facts and history.
1) First sentence: a strong hook of 12 words max.
2) 2 or 3 interesting facts from the article, with the why.
3) The LAST sentence must be a question so people comment; nothing after it. Do NOT ask people to follow.
COVER ("portada"): headline of 3 to 6 words, and "resaltar": 1 or 2 words exactly as they appear in the headline.
BUSQUEDAS: 3 short English phrases to search real photos of the topic (e.g. "Lake Baikal winter ice").
TRADUCCION_ES: a Spanish translation of the narration (only for the channel owner, it is not published).
Reply ONLY JSON: {"titulo": "...", "portada": "...", "resaltar": "...", "narracion": "...", "descripcion": "one line for the post", "hashtags": ["#facts", "..."], "busquedas": ["...", "...", "..."], "traduccion_es": "..."}"""

SISTEMA_VERIFICAR = """You are a very strict fact-checker. I give you a Wikipedia ARTICLE and a SCRIPT.
Go sentence by sentence. For every fact, number, name, date and comparison in the script, find the exact words in the article that support it
and put them in "evidencias" (short quotes). Any number that does not appear in the article with the same value, any comparison or
claim without an exact supporting quote, or anything exaggerated, is a problem: then "ok" must be false.
If there are problems, fix ONLY the sentences with problems and keep everything else the same: same friendly "you" tone, same opening hook,
same final question for comments (it must ALWAYS be the last sentence, nothing after it), 170 to 195 words. Do not turn it into an encyclopedia text or a list. Fix titulo/portada/resaltar if needed.
Reply ONLY JSON: {"evidencias": ["..."], "ok": true or false, "problemas": ["..."], "titulo": "...", "portada": "...", "resaltar": "...", "narracion": "..."}"""


def escribir_guion(art, extra=""):
    usuario = f"ARTICLE: {art['titulo']}\n\n{art['texto'][:6000]}\n\n{extra}"
    g, quien = preguntar(SISTEMA_GUION, usuario, temperatura=0.5)
    if len(str(g.get("narracion", "")).split()) < 140 or not g.get("portada"):
        raise SystemExit(f"Guion incompleto de {quien}")
    print(f"Guion ({quien}): {g['titulo']} ({len(g['narracion'].split())} palabras)")
    for ronda in range(3):
        v, quien = preguntar(SISTEMA_VERIFICAR, f"ARTICLE:\n{art['texto'][:6000]}\n\nSCRIPT:\n"
                             + json.dumps({k: g.get(k) for k in ("titulo", "portada", "resaltar", "narracion")},
                                          ensure_ascii=False), temperatura=0.2)
        if v.get("ok") is True or not v.get("problemas"):
            print(f"Verificación ({quien}): todo respaldado por el artículo")
            return g, []
        print(f"Verificación ({quien}) corrigió: {v['problemas']}")
        if len(str(v.get("narracion", "")).split()) < 140:
            break
        for k in ("titulo", "portada", "resaltar", "narracion"):
            if v.get(k):
                g[k] = v[k]
    raise SystemExit("El guion no pasó la verificación; hoy no se hace video")


# ---------- 5. Fotos reales de Wikimedia Commons ----------
def _filtrar(paginas):
    out = []
    for p in sorted(paginas, key=lambda x: x.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        nombre = p.get("title", "").lower()
        if ii.get("mime") != "image/jpeg" or ii.get("width", 0) < 900 or ii.get("height", 0) < 600:
            continue
        if any(x in nombre for x in ("logo", "map", "mapa", "flag", "bandera", "escudo", "coat of arms", "diagram",
                                      "locator", "border", "frontera", "chart", "graph", "icon", "signature", "firma")):
            continue
        meta = ii.get("extmetadata", {})
        autor = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()[:80]
        licencia = meta.get("LicenseShortName", {}).get("value", "")
        out.append({"url": ii.get("thumburl") or ii["url"], "titulo": p["title"], "autor": autor, "licencia": licencia})
    return out


IIPROP = {"prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600, "format": "json", "formatversion": 2}


def _imagenes_articulo(lang, titulo):
    q = urllib.parse.urlencode({"action": "query", "generator": "images", "titles": titulo, "gimlimit": 50,
                                "redirects": 1, **IIPROP})
    return _filtrar(bajar_json(f"https://{lang}.wikipedia.org/w/api.php?{q}").get("query", {}).get("pages", []))


def _commons(busqueda, limite=12):
    q = urllib.parse.urlencode({"action": "query", "generator": "search", "gsrnamespace": 6, "gsrsearch": busqueda,
                                "gsrlimit": limite, **IIPROP})
    return _filtrar(bajar_json(f"https://commons.wikimedia.org/w/api.php?{q}").get("query", {}).get("pages", []))


def fotos_commons(titulo, busquedas=(), solo_contar=False):
    """Primero las fotos del propio artículo en inglés, que siempre son del tema; luego búsquedas en Commons."""
    vistas, fotos = set(), []
    fuentes = [lambda: _imagenes_articulo("en", titulo)]
    if not solo_contar:
        fuentes += [lambda b=b: _commons(f"{b}") for b in busquedas]
    for fuente in fuentes:
        try:
            for f in fuente():
                if f["titulo"] not in vistas:
                    vistas.add(f["titulo"])
                    fotos.append(f)
        except Exception as e:
            print(f"  búsqueda de fotos falló: {e}")
    return len(fotos) if solo_contar else fotos


def bajar_fotos(fotos, cuantas=6):
    rutas, creditos = [], []
    for f in fotos:
        if len(rutas) >= cuantas:
            break
        try:
            img = Image.open(io.BytesIO(bajar(f["url"], timeout=60)))
            img = ImageOps.exif_transpose(img).convert("RGB")
            ruta = TMP / f"foto{len(rutas)}.jpg"
            img.save(ruta, quality=94)
            rutas.append(ruta)
            creditos.append(f"{f['titulo']} — {f['autor'] or 'Commons author'} ({f['licencia']})")
        except Exception as e:
            print(f"  foto falló: {e}")
    print(f"{len(rutas)} fotos reales listas")
    return rutas, creditos


def imagen_de_relleno(i):
    ruta = TMP / f"relleno{i}.jpg"
    img = Image.new("RGB", (W, H), NOCHE)
    d = ImageDraw.Draw(img)
    for k in range(0, H, s(90)):
        d.line([(0, k + i * 30), (W, k + s(300) + i * 30)], fill=(30, 27, 60), width=s(30))
    img.save(ruta, quality=92)
    return ruta


# ---------- 6. Diseño ----------
def cubrir(img):
    img = img.convert("RGB")
    r = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * r + 0.5), int(img.height * r + 0.5)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def cuadro_vertical(ruta_foto, i):
    """Foto horizontal -> fondo desenfocado + foto completa al centro (se ve nítida y sin cortar)."""
    foto = ImageOps.exif_transpose(Image.open(ruta_foto)).convert("RGB")
    if foto.height / foto.width >= 1.4:
        lienzo = cubrir(foto)
    else:
        lienzo = cubrir(foto).filter(ImageFilter.GaussianBlur(s(28)))
        lienzo = Image.blend(lienzo, Image.new("RGB", (W, H), NOCHE), 0.45)
        ancho = W
        alto = int(foto.height * ancho / foto.width)
        if alto > int(H * 0.62):
            alto = int(H * 0.62)
            ancho = int(foto.width * alto / foto.height)
        f2 = foto.resize((ancho, alto), Image.LANCZOS)
        lienzo.paste(f2, ((W - ancho) // 2, int(H * 0.40 - alto / 2)))
    ruta = TMP / f"cuadro{i}.jpg"
    lienzo.save(ruta, quality=94)
    return ruta


def degradado_abajo(img, desde=0.38, fuerza=235):
    capa = Image.new("RGBA", (W, H), NOCHE + (0,))
    d = ImageDraw.Draw(capa)
    y0 = int(H * desde)
    for y in range(y0, H):
        d.line([(0, y), (W, y)], fill=NOCHE + (int(fuerza * min(1, (y - y0) / (H * 0.35))),))
    return Image.alpha_composite(img.convert("RGBA"), capa)


def envolver(texto, f, ancho, d):
    lineas, actual = [], ""
    for p in texto.split():
        prueba = (actual + " " + p).strip()
        if d.textlength(prueba, font=f) <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas


def placa(d, xy, texto, f, pad=(14, 6)):
    x, y = xy
    l, t, r, b = d.textbbox((x, y), texto, font=f)
    d.rounded_rectangle([l - s(pad[0]), t - s(pad[1]), r + s(pad[0]), b + s(pad[1])], radius=s(10), fill=MENTA)
    d.text((x, y), texto, font=f, fill=NOCHE)
    return r + s(pad[0])


def marco(d, grosor):
    d.rectangle([0, 0, W - 1, H - 1], outline=MENTA, width=s(grosor))


def hacer_portada(foto, numero, titular, resaltar, categoria):
    img = degradado_abajo(cubrir(Image.open(foto)))
    d = ImageDraw.Draw(img)
    marco(d, 18)
    placa(d, (s(52), s(150)), f"#{numero:03d}", fuente(s(54)))
    titular, claves = titular.upper(), set((resaltar or "").upper().split())
    f = fuente(s(86))
    while True:
        lineas = envolver(titular, f, W - s(110), d)
        if len(lineas) <= 4 or f.size <= s(56):
            break
        f = fuente(f.size - s(6))
    alto_linea = int(f.size * 1.18)
    y = s(1000) - alto_linea * len(lineas)
    for linea in lineas:
        x = s(55)
        for palabra in linea.split():
            limpia = re.sub(r"[^\wÁÉÍÓÚÑÜ']", "", palabra)
            if limpia and limpia in claves:
                x = placa(d, (x + s(8), y), palabra, f, pad=(8, 2)) + s(10)
            else:
                d.text((x, y), palabra, font=f, fill=(255, 255, 255), stroke_width=s(2), stroke_fill=NOCHE)
                x += d.textlength(palabra + " ", font=f)
        y += alto_linea
    d.text((s(55), s(1035)), f"DID YOU KNOW? · {categoria}", font=fuente(s(28)), fill=MENTA)
    ruta = TMP / "portada.png"
    img.convert("RGB").save(ruta)
    return ruta


def hacer_marco(numero):
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    marco(d, 12)
    placa(d, (s(44), s(140)), f"#{numero:03d}", fuente(s(34)), pad=(12, 5))
    ruta = TMP / "marco.png"
    capa.save(ruta)
    return ruta


def hacer_cierre(foto, numero):
    img = cubrir(Image.open(foto)).filter(ImageFilter.GaussianBlur(s(18)))
    img = Image.alpha_composite(img.convert("RGBA"), Image.new("RGBA", (W, H), NOCHE + (215,)))
    d = ImageDraw.Draw(img)
    marco(d, 18)
    f1, f2 = fuente(s(64)), fuente(s(96))
    t1 = "FOLLOW FOR"
    d.text(((W - d.textlength(t1, font=f1)) / 2, s(470)), t1, font=f1, fill=(255, 255, 255))
    t2 = f"{SERIE} #{numero + 1:03d}"
    placa(d, ((W - d.textlength(t2, font=f2)) / 2, s(560)), t2, f2, pad=(18, 8))
    if USUARIO:
        f3 = fuente(s(40))
        d.text(((W - d.textlength(USUARIO, font=f3)) / 2, s(730)), USUARIO, font=f3, fill=MENTA)
    ruta = TMP / "cierre.png"
    img.convert("RGB").save(ruta)
    return ruta


# ---------- 7. Voz ----------
UNIDADES = [
    (r"(\d)\s*km\s*/\s*h\b", r"\1 kilometers per hour"), (r"\bkm\s*/\s*h\b", "kilometers per hour"),
    (r"(\d)\s*kWh\b", r"\1 kilowatt hours"), (r"(\d)\s*km\s*/\s*s\b", r"\1 kilometers per second"),
    (r"(\d)\s*m\s*/\s*s\b", r"\1 meters per second"), (r"(\d)\s*km²", r"\1 square kilometers"),
    (r"(\d)\s*sq\s*mi\b", r"\1 square miles"), (r"(\d)\s*m²", r"\1 square meters"),
    (r"(\d)\s*km\b", r"\1 kilometers"), (r"(\d)\s*kg\b", r"\1 kilograms"), (r"(\d)\s*lbs?\b", r"\1 pounds"),
    (r"(\d)\s*cm\b", r"\1 centimeters"), (r"(\d)\s*mm\b", r"\1 millimeters"), (r"(\d)\s*ft\b", r"\1 feet"),
    (r"(\d)\s*mi\b", r"\1 miles"), (r"(\d)\s*mph\b", r"\1 miles per hour"), (r"(\d)\s*°\s*F\b", r"\1 degrees Fahrenheit"),
    (r"(\d)\s*°\s*C\b", r"\1 degrees Celsius"), (r"(\d)\s*°", r"\1 degrees"), (r"(\d)\s*%", r"\1 percent"),
    (r"\bapprox\.", "approximately"), (r"\be\.g\.", "for example"), (r"\bi\.e\.", "that is"),
]


def para_hablar(texto):
    """Convierte abreviaturas y números raros en palabras para que la voz no lea letra por letra."""
    t = texto
    for _ in range(3):  # 3 600 000 -> 3600000 (en inglés el punto es decimal, no se toca)
        t = re.sub(r"(\d)[ \u00a0\u202f](?=\d{3}(?!\d))", r"\1", t)
    t = re.sub(r"(?<![\w-])-(\d)", r"minus \1", t)
    for patron, cambio in UNIDADES:
        t = re.sub(patron, cambio, t)
    t = t.replace("‑", "-").replace("–", ", ").replace("—", ", ")
    return t


async def _narrar(texto, voz, mp3, rate):
    import edge_tts
    try:
        com = edge_tts.Communicate(texto, voz, rate=rate, boundary="WordBoundary")
    except TypeError:
        com = edge_tts.Communicate(texto, voz, rate=rate)
    palabras = []
    with open(mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                ini = ch["offset"] / 1e7
                palabras.append((ini, ini + ch["duration"] / 1e7, ch["text"]))
    return palabras


def narrar(texto, rate="+0%"):
    mp3 = TMP / "voz.mp3"
    for voz in VOCES:
        try:
            palabras = asyncio.run(_narrar(texto, voz, mp3, rate))
            if mp3.stat().st_size > 10_000:
                print(f"Voz: {voz} ({rate})")
                return mp3, palabras
        except Exception as e:
            print(f"  voz {voz} falló: {e}")
    raise SystemExit("No se pudo generar la voz")


# ---------- 8. Subtítulos ----------
def t_ass(x):
    h, rest = divmod(max(x, 0), 3600)
    m, x = divmod(rest, 60)
    return f"{int(h)}:{int(m):02d}:{x:05.2f}"


def subtitulos(palabras, texto, dur_voz, desde):
    if not palabras:
        tokens = texto.split()
        paso = dur_voz / max(len(tokens), 1)
        palabras = [(i * paso, (i + 1) * paso, w) for i, w in enumerate(tokens)]
    trozos, actual = [], []
    for p in palabras:
        actual.append(p)
        if len(actual) == 3 or re.search(r"[.,;:?!]$", p[2]):
            trozos.append(actual)
            actual = []
    if actual:
        trozos.append(actual)
    menta, blanco = hexass(MENTA), hexass((255, 255, 255))
    lineas = []
    for i, tr in enumerate(trozos):
        fin_trozo = trozos[i + 1][0][0] if i + 1 < len(trozos) else tr[-1][1] + 0.3
        for j, (ini, _, _) in enumerate(tr):
            fin = tr[j + 1][0] if j + 1 < len(tr) else fin_trozo
            if fin <= desde:
                continue
            partes = []
            for k, (_, _, w) in enumerate(tr):
                w = w.upper().replace("{", "(").replace("}", ")")
                partes.append(f"{{\\c{menta}}}{w}{{\\c{blanco}}}" if k == j else w)
            lineas.append(f"Dialogue: 0,{t_ass(max(ini, desde))},{t_ass(fin)},Sub,,0,0,0,,{' '.join(partes)}")
    ass = TMP / "subs.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{nombre_fuente()},{s(84)},{blanco},{blanco},{hexass(NOCHE)},&H64000000&,1,0,0,0,100,100,0,0,1,{s(6)},0,2,{s(60)},{s(60)},{s(400)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lineas) + "\n", encoding="utf-8")
    return ass


# ---------- 9. Video ----------
def armar_video(portada, cuadros_img, marco_png, cierre, mp3, ass, salida):
    dur_voz = duracion(mp3)
    total = dur_voz + CIERRE_SEG
    n = len(cuadros_img)
    cuadros = int(round((dur_voz - PORTADA_SEG) / n * FPS))
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats", "-loop", "1", "-t", f"{PORTADA_SEG}", "-i", str(portada)]
    for img in cuadros_img:
        cmd += ["-i", str(img)]
    cmd += ["-loop", "1", "-i", str(marco_png), "-loop", "1", "-t", f"{CIERRE_SEG}", "-i", str(cierre),
            "-i", str(mp3), "-f", "lavfi", "-t", f"{total:.2f}", "-i", "anoisesrc=color=pink:amplitude=0.03:sample_rate=44100"]
    i_marco, i_cierre, i_voz, i_amb = n + 1, n + 2, n + 3, n + 4
    f = [f"[0:v]scale={W}:{H},setsar=1,fps={FPS},format=yuv420p[por]"]
    for i in range(n):
        zoom = "min(zoom+0.0005,1.08)" if i % 2 == 0 else "if(eq(on,0),1.08,max(zoom-0.0005,1.0))"
        f.append(f"[{i + 1}:v]scale={int(W * 1.5)}:{int(H * 1.5)},"
                 f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={cuadros}:s={W}x{H}:fps={FPS},"
                 f"setsar=1,format=yuv420p[h{i}]")
    f.append("".join(f"[h{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[hist0]")
    f.append(f"[hist0][{i_marco}:v]overlay=0:0:shortest=1,format=yuv420p[hist]")
    f.append(f"[{i_cierre}:v]scale={W}:{H},setsar=1,fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.25[cie]")
    f.append(f"[por][hist][cie]concat=n=3:v=1:a=0,ass={ass.name}:fontsdir={RAIZ / 'fuentes'}[vout]")
    f.append(f"[{i_voz}:a]apad=pad_dur={CIERRE_SEG},volume=1.5[voz]")
    f.append(f"[{i_amb}:a]highpass=f=200,lowpass=f=3000,volume=0.25[amb]")
    f.append("[voz][amb]amix=inputs=2:duration=first:dropout_transition=0,volume=1.6[aout]")
    cmd += ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.2f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(salida)]
    correr(cmd, cwd=TMP)


def main():
    SAL.mkdir(exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    (RAIZ / "fuentes").mkdir(exist_ok=True)
    hoy = os.environ.get("FECHA_TURNO") or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4))).strftime("%Y-%m-%d")
    reg = registro()
    numero = len(reg) + 1
    categoria = CATEGORIAS[(numero - 1) % len(CATEGORIAS)]

    if PRUEBA:
        art = {"titulo": "Prueba", "url": ""}
        g = {"titulo": "Prueba", "portada": "Este lago guarda un secreto", "resaltar": "secreto",
             "descripcion": "Prueba", "hashtags": ["#facts"],
             "narracion": ("Did you know this lake is way older than you think? " * 14).strip()}
        revisar, creditos = [], []
        fotos = [imagen_de_relleno(i) for i in range(5)]
        mp3 = TMP / "voz.mp3"
        correr(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=180:duration=62",
                "-c:a", "libmp3lame", str(mp3)])
        palabras = []
    else:
        usados = [l.split("|")[3].strip() for l in reg]
        print(f"{SERIE} #{numero:03d} · categoría: {categoria}", flush=True)
        art = escoger_tema(categoria, usados)
        g, revisar = escribir_guion(art)
        cierre_hablado = f" Follow for {SERIE.lower()} number {numero + 1}."
        hablado = para_hablar(g["narracion"]) + cierre_hablado
        mp3, palabras = narrar(hablado)
        if duracion(mp3) + CIERRE_SEG < 61.5:
            print("Quedó corto, se narra más despacio")
            mp3, palabras = narrar(hablado, rate="-8%")
        if duracion(mp3) + CIERRE_SEG < 61.5:
            raise SystemExit("La narración no llega al minuto; hoy no se hace video")
        fotos, creditos = bajar_fotos(fotos_commons(art["titulo"], g.get("busquedas", [])))
        if len(fotos) < 3:
            raise SystemExit("No hay suficientes fotos reales del tema; hoy no se hace video")

    portada = hacer_portada(fotos[0], numero, g["portada"], g.get("resaltar", ""), categoria)
    cuadros_img = [cuadro_vertical(f, i) for i, f in enumerate(fotos)]
    marco_png = hacer_marco(numero)
    cierre = hacer_cierre(fotos[-1], numero)
    ass = subtitulos(palabras, g["narracion"], duracion(mp3), PORTADA_SEG)
    video = SAL / "video.mp4"
    armar_video(portada, cuadros_img, marco_png, cierre, mp3, ass, video)

    Image.open(portada).convert("RGB").save(SAL / "portada.jpg", quality=92)
    tags = " ".join(h if h.startswith("#") else "#" + h for h in g.get("hashtags", []))
    for t in ["#facts", "#didyouknow", "#funfacts"]:
        if t not in tags:
            tags += " " + t
    (SAL / "descripcion.txt").write_text(
        f"{g['titulo']}\n\n{g.get('descripcion', '')}\n\nImages: Wikimedia Commons\n\n{tags.strip()}\n", encoding="utf-8")
    nota = ("\n\nREVISAR ANTES DE PUBLICAR: " + "; ".join(map(str, revisar))) if revisar else ""
    (SAL / "guion.txt").write_text(
        f"{SERIE} #{numero:03d}\nFuente (solo para ti, no va en el post): {art['titulo']} — {art['url']}\n\n"
        f"{g['narracion']}{nota}\n\nEN ESPAÑOL (solo para ti):\n{g.get('traduccion_es', '')}\n\nCréditos de las fotos:\n" + "\n".join(creditos) + "\n", encoding="utf-8")
    if not PRUEBA:
        with open(RAIZ / "registro.txt", "a", encoding="utf-8") as fh:
            fh.write(f"{hoy} | #{numero:03d} | {categoria} | {art['titulo']} | {os.environ.get('TURNO', 'M')}\n")
    print(f"Listo: {video} ({duracion(video):.1f} s)")


if __name__ == "__main__":
    main()
