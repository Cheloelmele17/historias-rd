#!/usr/bin/env python3
# Video diario de curiosidades (países, tecnología, ciencia, historia...) con estilo propio "menta y noche".
#   guion  -> Pollinations texto (gratis, sin cuenta) o Gemini si hay clave GEMINI_API_KEY
#   fotos  -> Pollinations (gratis, sin cuenta)
#   voz    -> edge-tts (voces de Microsoft, gratis)
#   video  -> Pillow + ffmpeg (portada, marco, número, subtítulos con la palabra resaltada, cierre)
# Resultado: salida/video.mp4, salida/portada.jpg y salida/descripcion.txt
# Prueba sin internet: python3 hacer_video.py --prueba-local
import asyncio, datetime, json, os, pathlib, random, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ===== Ajustes de marca (cambiar aquí) =====
USUARIO = os.environ.get("USUARIO_TIKTOK", "")        # ej. "@datodiario" (vacío = no se muestra)
MENTA = (46, 242, 194)                                   # #2EF2C2
NOCHE = (20, 17, 43)                                     # #14112B
SERIE = "DATO"
# ===========================================

RAIZ = pathlib.Path(__file__).resolve().parent
SAL = RAIZ / "salida"
TMP = SAL / "tmp"
W, H, FPS = 720, 1280, 30
PORTADA_SEG, CIERRE_SEG = 1.3, 2.2
VOCES = [os.environ.get("VOZ", "es-MX-JorgeNeural"), "es-DO-EmilioNeural", "es-US-AlonsoNeural"]
ESTILO = (", photorealistic, cinematic lighting, vivid colors, sharp focus, high detail, vertical composition,"
          " no text, no letters, no watermark, no logo")
CATEGORIAS = ["PAÍSES", "TECNOLOGÍA", "CIENCIA", "CUERPO HUMANO", "ANIMALES", "HISTORIA", "ESPACIO",
              "INVENTOS", "CIUDADES", "NATURALEZA", "COMIDA DEL MUNDO", "RÉCORDS"]
PRUEBA = "--prueba-local" in sys.argv


def hexass(rgb):  # color para subtítulos ASS (&HBBGGRR&)
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


# ---------- 1. Número y tema ----------
def registro():
    reg = RAIZ / "registro.txt"
    if not reg.exists():
        return []
    return [l for l in reg.read_text(encoding="utf-8").splitlines() if l.count("|") >= 3]


def escoger_categoria(numero):
    return CATEGORIAS[(numero - 1) % len(CATEGORIAS)]


# ---------- 2. Guion ----------
SISTEMA = """Eres guionista de un canal de TikTok de curiosidades en español latino, para público dominicano y latinoamericano.
Cada video explica UN dato curioso real, sorprendente y fácil de comprobar (de cualquier país, tecnología, ciencia, historia, animales, espacio, etc.).
REGLAS DE VERDAD: usa solo datos ampliamente conocidos y verificables. Si no estás seguro de una cifra exacta, no la pongas: usa "más de", "casi" o descríbelo sin número. Nada de mitos presentados como hechos. Nada de política, religión, tragedias recientes ni personas privadas.
NARRACIÓN (entre 175 y 200 palabras, para durar más de un minuto):
1) Primera frase: gancho fuerte que dé curiosidad (pregunta o afirmación sorprendente), máximo 12 palabras.
2) Explica el dato con 2 o 3 detalles interesantes y el porqué.
3) Termina con una pregunta para que comenten. NO pidas que te sigan (eso se agrega aparte).
Tono: cercano, claro, con ritmo, frases cortas. Español neutro con calidez caribeña, sin groserías.
PORTADA: un titular de 3 a 6 palabras que dé ganas de ver el video, y la palabra o frase corta (1 o 2 palabras, tal cual aparece en el titular) que se resalta.
ESCENAS: exactamente 6 descripciones en INGLÉS para un generador de imágenes fotorrealistas, en el orden de la narración. Cada una: qué se ve, concreto (lugar, objeto, animal, luz). Sin texto en la imagen, sin personas famosas reales.
Escribe TODO en español, también el título.
Responde SOLO con JSON:
{"titulo": "...", "portada": "...", "resaltar": "...", "narracion": "...", "escenas": ["...","...","...","...","...","..."], "descripcion": "una línea para el post", "hashtags": ["#curiosidades", "..."]}"""


def _pedir(url, cuerpo, headers):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "dato-diario/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            texto = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code}: {e.read()[:200]!r}")
    try:  # respuesta estilo OpenAI o texto directo
        texto = json.loads(texto)["choices"][0]["message"]["content"]
    except Exception:
        pass
    return texto


def proveedores():
    # 1) Gemini (opcional, gratis con clave de Google AI Studio en el secreto GEMINI_API_KEY)
    clave = os.environ.get("GEMINI_API_KEY", "").strip()
    if clave:
        for modelo in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
            yield (f"gemini:{modelo}", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                   {"model": modelo, "temperature": 0.9, "response_format": {"type": "json_object"}},
                   {"Authorization": f"Bearer {clave}"})
    # 2) Pollinations (gratis, sin cuenta)
    yield ("pollinations:openai", "https://text.pollinations.ai/openai",
           {"model": "openai", "temperature": 0.9, "response_format": {"type": "json_object"}}, {})
    yield ("pollinations:texto", "https://text.pollinations.ai/", {"model": "openai", "jsonMode": True}, {})


def pedir_guion(categoria, anteriores, extra=""):
    usados = "\n".join(f"- {t}" for t in anteriores[-80:]) or "(ninguno todavía)"
    pedido = (f"Categoría de hoy: {categoria}.\nNo repitas ninguno de estos temas ya publicados:\n{usados}\n{extra}")
    mensajes = [{"role": "system", "content": SISTEMA}, {"role": "user", "content": pedido}]
    ultimo_error = None
    for intento in range(3):
        for nombre, url, cuerpo, headers in proveedores():
            try:
                texto = _pedir(url, {**cuerpo, "messages": mensajes}, headers)
                g = json.loads(re.search(r"\{.*\}", texto, re.S).group(0))
                palabras = len(g["narracion"].split())
                if palabras < 150 or len(g["escenas"]) < 4 or not g.get("portada"):
                    raise ValueError(f"guion incompleto: {palabras} palabras, {len(g['escenas'])} escenas")
                print(f"Guion con {nombre}: {g['titulo']} ({palabras} palabras)")
                return g
            except Exception as e:
                ultimo_error = e
                print(f"  {nombre} falló: {str(e)[:300]}")
                time.sleep(16)
    raise SystemExit(f"No se pudo escribir el guion: {ultimo_error}")


VERIFICAR = """Eres un verificador de datos muy estricto. Revisa el guion de un video de curiosidades.
Marca como problema cualquier afirmación falsa, exagerada o dudosa (récords, "el más grande del mundo", cifras, fechas).
Si hay problemas, reescribe la narración (misma longitud y estilo) dejando solo lo que sea cierto y verificable, y corrige el título y el titular de portada si hace falta. Todo en español.
Responde SOLO con JSON: {"ok": true o false, "problemas": ["..."], "titulo": "...", "portada": "...", "resaltar": "...", "narracion": "..."}"""


def verificar(g):
    contenido = json.dumps({k: g.get(k) for k in ("titulo", "portada", "resaltar", "narracion")}, ensure_ascii=False)
    mensajes = [{"role": "system", "content": VERIFICAR}, {"role": "user", "content": contenido}]
    for nombre, url, cuerpo, headers in proveedores():
        try:
            v = json.loads(re.search(r"\{.*\}", _pedir(url, {**cuerpo, "messages": mensajes}, headers), re.S).group(0))
            if v.get("ok") is True or not v.get("problemas"):
                print(f"Verificación ({nombre}): sin problemas")
                return g, []
            print(f"Verificación ({nombre}) corrigió: {v['problemas']}")
            if len(str(v.get("narracion", "")).split()) >= 140:
                for k in ("titulo", "portada", "resaltar", "narracion"):
                    if v.get(k):
                        g[k] = v[k]
            return g, v["problemas"]
        except Exception as e:
            print(f"  verificación con {nombre} falló: {str(e)[:200]}")
            time.sleep(16)
    return g, ["no se pudo verificar"]


# ---------- 3. Imágenes ----------
def es_imagen(d):
    return d[:3] == b"\xff\xd8\xff" or d[:8] == b"\x89PNG\r\n\x1a\n" or d[8:12] == b"WEBP"


def bajar_imagenes(escenas):
    rutas, semilla = [], random.randint(1, 10_000_000)
    for i, escena in enumerate(escenas):
        ruta = TMP / f"img{i}.jpg"
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(escena + ESTILO, safe="") +
               f"?width={W}&height={H}&seed={semilla + i}&nologo=true")
        for intento in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "dato-diario/1.0"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    datos = r.read()
                if not es_imagen(datos):
                    raise ValueError("no llegó una imagen")
                Image.open(__import__("io").BytesIO(datos)).convert("RGB").save(ruta, quality=92)
                rutas.append(ruta)
                print(f"Imagen {i + 1}/{len(escenas)} lista")
                break
            except Exception as e:
                print(f"  imagen {i + 1}, intento {intento + 1} falló: {e}")
                time.sleep(20)
        time.sleep(16)  # el plan gratis permite una imagen cada 15 segundos
    return rutas


def imagen_de_relleno(i):
    ruta = TMP / f"relleno{i}.jpg"
    img = Image.new("RGB", (W, H), NOCHE)
    d = ImageDraw.Draw(img)
    for k in range(0, H, 90):
        d.line([(0, k + i * 20), (W, k + 300 + i * 20)], fill=(30, 27, 60), width=30)
    img.save(ruta, quality=92)
    return ruta


def ajustar(img):  # recorta/escala a 720x1280
    img = img.convert("RGB")
    r = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * r + 0.5), int(img.height * r + 0.5)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


# ---------- 4. Diseño: portada, marco y cierre ----------
def degradado_abajo(img, desde=0.38, fuerza=235):
    capa = Image.new("RGBA", (W, H), NOCHE + (0,))
    d = ImageDraw.Draw(capa)
    y0 = int(H * desde)
    for y in range(y0, H):
        a = int(fuerza * min(1, (y - y0) / (H * 0.35)))
        d.line([(0, y), (W, y)], fill=NOCHE + (a,))
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
    d.rounded_rectangle([l - pad[0], t - pad[1], r + pad[0], b + pad[1]], radius=10, fill=MENTA)
    d.text((x, y), texto, font=f, fill=NOCHE)
    return r + pad[0]


def marco(d, grosor):
    d.rectangle([0, 0, W - 1, H - 1], outline=MENTA, width=grosor)


def hacer_portada(img_fondo, numero, titular, resaltar, categoria):
    img = degradado_abajo(ajustar(Image.open(img_fondo)))
    d = ImageDraw.Draw(img)
    marco(d, 18)
    placa(d, (52, 150), f"#{numero:03d}", fuente(54))
    titular, resaltar = titular.upper(), (resaltar or "").upper().strip()
    f = fuente(86)
    while True:
        lineas = envolver(titular, f, W - 110, d)
        if len(lineas) <= 4 or f.size <= 56:
            break
        f = fuente(f.size - 6)
    alto_linea = int(f.size * 1.18)
    y = 1000 - alto_linea * len(lineas)
    claves = set(resaltar.split())
    for linea in lineas:
        x = 55
        for palabra in linea.split():
            limpia = re.sub(r"[^\wÁÉÍÓÚÑÜ]", "", palabra)
            if limpia and limpia in claves:
                x = placa(d, (x + 8, y), palabra, f, pad=(8, 2)) + 10
            else:
                d.text((x, y), palabra, font=f, fill=(255, 255, 255), stroke_width=2, stroke_fill=NOCHE)
                x += d.textlength(palabra + " ", font=f)
        y += alto_linea
    d.text((55, 1035), f"CURIOSIDADES · {categoria}", font=fuente(28), fill=MENTA)
    ruta = TMP / "portada.png"
    img.convert("RGB").save(ruta)
    return ruta


def hacer_marco(numero):
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    marco(d, 12)
    placa(d, (44, 140), f"#{numero:03d}", fuente(34), pad=(12, 5))
    ruta = TMP / "marco.png"
    capa.save(ruta)
    return ruta


def hacer_cierre(img_fondo, numero):
    img = ajustar(Image.open(img_fondo)).filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img.convert("RGBA"), Image.new("RGBA", (W, H), NOCHE + (215,)))
    d = ImageDraw.Draw(img)
    marco(d, 18)
    f1, f2 = fuente(64), fuente(96)
    for texto, f, y, color in [("SÍGUEME PARA EL", f1, 470, (255, 255, 255)), (f"{SERIE} #{numero + 1:03d}", f2, 560, None)]:
        x = (W - d.textlength(texto, font=f)) / 2
        if color:
            d.text((x, y), texto, font=f, fill=color)
        else:
            placa(d, (x, y), texto, f, pad=(18, 8))
    if USUARIO:
        f3 = fuente(40)
        d.text(((W - d.textlength(USUARIO, font=f3)) / 2, 730), USUARIO, font=f3, fill=MENTA)
    ruta = TMP / "cierre.png"
    img.convert("RGB").save(ruta)
    return ruta


# ---------- 5. Voz ----------
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


def narrar(texto, rate="+6%"):
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


# ---------- 6. Subtítulos con la palabra que suena resaltada ----------
def t_ass(s):
    h, rest = divmod(max(s, 0), 3600)
    m, s = divmod(rest, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


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
Style: Sub,{nombre_fuente()},84,{blanco},{blanco},{hexass(NOCHE)},&H64000000&,1,0,0,0,100,100,0,0,1,6,0,2,60,60,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lineas) + "\n", encoding="utf-8")
    return ass


# ---------- 7. Video ----------
def armar_video(portada, imagenes, marco_png, cierre, mp3, ass, salida):
    dur_voz = duracion(mp3)
    total = dur_voz + CIERRE_SEG
    historia = dur_voz - PORTADA_SEG
    n = len(imagenes)
    cuadros = int(round(historia / n * FPS))
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
           "-loop", "1", "-t", f"{PORTADA_SEG}", "-i", str(portada)]
    for img in imagenes:
        cmd += ["-i", str(img)]
    cmd += ["-loop", "1", "-i", str(marco_png),
            "-loop", "1", "-t", f"{CIERRE_SEG}", "-i", str(cierre),
            "-i", str(mp3),
            "-f", "lavfi", "-t", f"{total:.2f}", "-i", "anoisesrc=color=pink:amplitude=0.03:sample_rate=44100"]
    i_marco, i_cierre, i_voz, i_amb = n + 1, n + 2, n + 3, n + 4
    f = [f"[0:v]scale={W}:{H},setsar=1,fps={FPS},format=yuv420p[por]"]
    for i in range(n):
        zoom = "min(zoom+0.0007,1.12)" if i % 2 == 0 else "if(eq(on,0),1.12,max(zoom-0.0007,1.0))"
        f.append(f"[{i + 1}:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                 f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={cuadros}:s={W}x{H}:fps={FPS},"
                 f"setsar=1,format=yuv420p[h{i}]")
    f.append("".join(f"[h{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[hist0]")
    f.append(f"[hist0][{i_marco}:v]overlay=0:0:shortest=1,format=yuv420p[hist]")
    f.append(f"[{i_cierre}:v]scale={W}:{H},setsar=1,fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.25[cie]")
    f.append(f"[por][hist][cie]concat=n=3:v=1:a=0,ass={ass.name}:fontsdir={RAIZ / 'fuentes'}[vout]")
    f.append(f"[{i_voz}:a]apad=pad_dur={CIERRE_SEG},volume=1.5[voz]")
    f.append(f"[{i_amb}:a]highpass=f=200,lowpass=f=3000,volume=0.25[amb]")
    f.append("[voz][amb]amix=inputs=2:duration=first:dropout_transition=0,volume=1.6[aout]")
    cmd += ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]",
            "-t", f"{total:.2f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(salida)]
    correr(cmd, cwd=TMP)


def main():
    SAL.mkdir(exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    (RAIZ / "fuentes").mkdir(exist_ok=True)
    hoy = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4))).strftime("%Y-%m-%d")
    reg = registro()
    numero = len(reg) + 1
    categoria = escoger_categoria(numero)

    if PRUEBA:
        g = {"titulo": "Prueba", "portada": "Este país no tiene mosquitos", "resaltar": "no tiene",
             "descripcion": "Prueba", "hashtags": ["#curiosidades"],
             "narracion": ("¿Sabías que hay un país donde no vas a encontrar ni un solo mosquito? " * 12).strip(),
             "escenas": ["a"] * 6}
        imagenes = [imagen_de_relleno(i) for i in range(6)]
        mp3 = TMP / "voz.mp3"
        correr(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=180:duration=62",
                "-c:a", "libmp3lame", str(mp3)])
        palabras, revisar = [], []
    else:
        anteriores = [l.split("|")[3].strip() for l in reg]
        print(f"{SERIE} #{numero:03d} · categoría: {categoria}")
        g, revisar = verificar(pedir_guion(categoria, anteriores))
        cierre_hablado = f" Sígueme para el {SERIE.lower()} número {numero + 1}."
        mp3, palabras = narrar(g["narracion"] + cierre_hablado)
        if duracion(mp3) + CIERRE_SEG < 61.5:  # que pase del minuto
            print("Quedó corto, se narra más despacio")
            mp3, palabras = narrar(g["narracion"] + cierre_hablado, rate="-6%")
        if duracion(mp3) + CIERRE_SEG < 61.5:
            print("Sigue corto, se pide un guion más largo")
            g, revisar = verificar(pedir_guion(categoria, anteriores, "La narración anterior quedó corta: escribe entre 195 y 215 palabras."))
            mp3, palabras = narrar(g["narracion"] + cierre_hablado)
        imagenes = bajar_imagenes(g["escenas"][:6])
        while len(imagenes) < 4:
            imagenes.append(imagen_de_relleno(len(imagenes)))

    portada = hacer_portada(imagenes[0], numero, g["portada"], g.get("resaltar", ""), categoria)
    marco_png = hacer_marco(numero)
    cierre = hacer_cierre(imagenes[-1], numero)
    ass = subtitulos(palabras, g["narracion"], duracion(mp3), PORTADA_SEG)
    video = SAL / "video.mp4"
    armar_video(portada, imagenes, marco_png, cierre, mp3, ass, video)

    Image.open(portada).convert("RGB").save(SAL / "portada.jpg", quality=92)
    tags = " ".join(h if h.startswith("#") else "#" + h for h in g.get("hashtags", []))
    for t in ["#curiosidades", "#sabiasque", "#datocurioso"]:
        if t not in tags:
            tags += " " + t
    (SAL / "descripcion.txt").write_text(
        f"{SERIE} #{numero:03d} · {g['titulo']}\n\n{g.get('descripcion', '')}\n\n{tags.strip()}\n", encoding="utf-8")
    nota = ("\n\nREVISAR ANTES DE PUBLICAR: " + "; ".join(map(str, revisar))) if revisar else ""
    (SAL / "guion.txt").write_text(g["narracion"] + nota + "\n", encoding="utf-8")
    if not PRUEBA:
        with open(RAIZ / "registro.txt", "a", encoding="utf-8") as fh:
            fh.write(f"{hoy} | #{numero:03d} | {categoria} | {g['titulo']}\n")
    print(f"Listo: {video} ({duracion(video):.1f} s)")


if __name__ == "__main__":
    main()
