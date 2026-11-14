#!/usr/bin/env python3
# Arma un video vertical de leyendas y misterio dominicano, todo con herramientas gratis:
#   guion  -> GitHub Models (con el GITHUB_TOKEN de Actions, sin claves extra)
#   fotos  -> Pollinations (gratis, sin cuenta)
#   voz    -> edge-tts (voces de Microsoft, gratis)
#   video  -> ffmpeg (zoom suave, subtítulos grandes, ambiente de suspenso)
# Resultado: salida/video.mp4 y salida/descripcion.txt
# Prueba sin internet: python3 hacer_video.py --prueba-local
import asyncio, datetime, json, os, pathlib, random, re, subprocess, sys, time, urllib.parse, urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent
SAL = RAIZ / "salida"
TMP = SAL / "tmp"
ANCHO, ALTO, FPS = 720, 1280, 30
VOCES = [os.environ.get("VOZ", "es-DO-EmilioNeural"), "es-DO-RamonaNeural", "es-MX-JorgeNeural"]
MODELOS = ["openai/gpt-4.1-mini", "openai/gpt-4o-mini", "openai/gpt-4o"]
ESTILO = (", cinematic dark folk horror illustration, rural Dominican Republic, Caribbean countryside,"
          " moonlight, fog, dramatic shadows, highly detailed, vertical composition, no text, no watermark, no gore")
PRUEBA = "--prueba-local" in sys.argv


def correr(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd)[:300], flush=True)
    subprocess.run(cmd, check=True, **kw)


def duracion(ruta):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


# ---------- 1. Tema ----------
def escoger_tema():
    temas = [l.strip() for l in (RAIZ / "temas.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    reg = RAIZ / "registro.txt"
    usados = set()
    if reg.exists():
        for l in reg.read_text(encoding="utf-8").splitlines():
            partes = [p.strip() for p in l.split("|")]
            if len(partes) >= 2:
                usados.add(partes[1])
    libres = [t for t in temas if t not in usados]
    if not libres:  # ya se usaron todos: se empieza otra vuelta con historias nuevas
        libres = temas
    return libres[0]


# ---------- 2. Guion ----------
SISTEMA = """Eres guionista de TikTok de leyendas, misterio y terror dominicano.
Escribe en español dominicano natural, como alguien del campo contando una historia de noche. Nada de groserías, sangre ni violencia gráfica.
Estructura de la narración (entre 130 y 170 palabras, unos 60 segundos):
1) Primera frase: un gancho fuerte e inquietante (una pregunta o una afirmación que dé escalofrío).
2) Desarrollo con detalles del campo dominicano.
3) Un giro o final que deje con ganas de más.
4) Cierre corto pidiendo que comenten, por ejemplo: "¿Tú crees en eso? Te leo en los comentarios."
Si el tema es una leyenda conocida, cuéntala como la cuentan los viejos ("cuentan que..."), sin inventar fechas ni datos históricos.
Si dice "Historia original", inventa una historia nueva, que no use nombres de personas reales.
Además escribe exactamente 6 escenas en INGLÉS para un generador de imágenes, en el orden de la historia. Cada escena: una frase concreta de lo que se ve (lugar, personaje, luz). Sin texto en la imagen, sin sangre.
Responde SOLO con JSON con estas claves:
{"titulo": "...", "narracion": "...", "escenas": ["...", "...", "...", "...", "...", "..."], "descripcion": "una línea para el post de TikTok", "hashtags": ["#leyendasdominicanas", "..."]}"""


def pedir_guion(tema):
    token = os.environ.get("GITHUB_TOKEN", "")
    ultimo_error = None
    for intento in range(2):
        for modelo in MODELOS:
            cuerpo = json.dumps({
                "model": modelo,
                "temperature": 0.9,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SISTEMA},
                             {"role": "user", "content": f"Tema: {tema}"}],
            }).encode()
            req = urllib.request.Request("https://models.github.ai/inference/chat/completions", data=cuerpo,
                                         headers={"Authorization": f"Bearer {token}",
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    texto = json.load(r)["choices"][0]["message"]["content"]
                g = json.loads(re.search(r"\{.*\}", texto, re.S).group(0))
                palabras = len(g["narracion"].split())
                if not (90 <= palabras <= 230) or len(g["escenas"]) < 4:
                    raise ValueError(f"guion fuera de medida: {palabras} palabras, {len(g['escenas'])} escenas")
                print(f"Guion con {modelo}: {g['titulo']} ({palabras} palabras)")
                return g
            except Exception as e:
                ultimo_error = e
                print(f"  {modelo} falló: {e}")
                time.sleep(5)
    raise SystemExit(f"No se pudo escribir el guion: {ultimo_error}")


# ---------- 3. Imágenes ----------
def es_imagen(datos):
    return datos[:3] == b"\xff\xd8\xff" or datos[:8] == b"\x89PNG\r\n\x1a\n" or datos[8:12] == b"WEBP"


def bajar_imagenes(escenas):
    rutas = []
    semilla = random.randint(1, 10_000_000)
    for i, escena in enumerate(escenas):
        ruta = TMP / f"img{i}.jpg"
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(escena + ESTILO, safe="") +
               f"?width={ANCHO}&height={ALTO}&seed={semilla + i}&nologo=true")
        for intento in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "historias-rd/1.0"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    datos = r.read()
                if not es_imagen(datos):
                    raise ValueError("no llegó una imagen")
                ruta.write_bytes(datos)
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
    colores = ["0x0b1020", "0x140b0b", "0x0b140f", "0x120b16"]
    correr(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            f"color=c={colores[i % 4]}:s={ANCHO}x{ALTO},noise=alls=25:allf=t,vignette",
            "-frames:v", "1", str(ruta)])
    return ruta


# ---------- 4. Voz ----------
async def _narrar(texto, voz, mp3):
    import edge_tts
    try:
        com = edge_tts.Communicate(texto, voz, rate="+4%", boundary="WordBoundary")
    except TypeError:
        com = edge_tts.Communicate(texto, voz, rate="+4%")
    palabras = []
    with open(mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                ini = ch["offset"] / 1e7
                palabras.append((ini, ini + ch["duration"] / 1e7, ch["text"]))
    return palabras


def narrar(texto):
    mp3 = TMP / "voz.mp3"
    for voz in VOCES:
        try:
            palabras = asyncio.run(_narrar(texto, voz, mp3))
            if mp3.stat().st_size > 10_000:
                print(f"Voz: {voz}")
                return mp3, palabras
        except Exception as e:
            print(f"  voz {voz} falló: {e}")
    raise SystemExit("No se pudo generar la voz")


# ---------- 5. Subtítulos ----------
def t_ass(s):
    h, rest = divmod(max(s, 0), 3600)
    m, s = divmod(rest, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def subtitulos(palabras, texto, dur_voz):
    if not palabras:  # sin tiempos de la voz: se reparten las palabras parejo
        tokens = texto.split()
        paso = dur_voz / max(len(tokens), 1)
        palabras = [(i * paso, (i + 1) * paso, w) for i, w in enumerate(tokens)]
    trozos, actual = [], []
    for p in palabras:
        actual.append(p)
        if len(actual) == 3 or re.search(r"[.,;:?!¿¡]$", p[2]):
            trozos.append(actual)
            actual = []
    if actual:
        trozos.append(actual)
    lineas = []
    for i, tr in enumerate(trozos):
        ini = tr[0][0]
        fin = trozos[i + 1][0][0] if i + 1 < len(trozos) else tr[-1][1] + 0.3
        txt = " ".join(w for _, _, w in tr).upper().replace("{", "(").replace("}", ")")
        lineas.append(f"Dialogue: 0,{t_ass(ini)},{t_ass(fin)},Sub,,0,0,0,,{txt}")
    ass = TMP / "subs.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {ANCHO}
PlayResY: {ALTO}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,DejaVu Sans,66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,50,50,330,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lineas) + "\n", encoding="utf-8")
    return ass


# ---------- 6. Video ----------
def armar_video(imagenes, mp3, ass, salida):
    dur_voz = duracion(mp3)
    total = dur_voz + 1.2
    n = len(imagenes)
    seg = total / n
    cuadros = int(round(seg * FPS))
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats"]
    for img in imagenes:
        cmd += ["-i", str(img)]
    cmd += ["-i", str(mp3),
            "-f", "lavfi", "-t", f"{total:.2f}", "-i", "anoisesrc=color=brown:amplitude=0.08:sample_rate=44100"]
    filtros = []
    for i in range(n):
        zoom = "min(zoom+0.0008,1.15)" if i % 2 == 0 else "if(eq(on,0),1.15,max(zoom-0.0008,1.0))"
        filtros.append(
            f"[{i}:v]scale={ANCHO * 2}:{ALTO * 2}:force_original_aspect_ratio=increase,crop={ANCHO * 2}:{ALTO * 2},"
            f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={cuadros}:s={ANCHO}x{ALTO}:fps={FPS},"
            f"setsar=1,format=yuv420p[v{i}]")
    filtros.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,"
                   f"eq=contrast=1.08:saturation=0.85,vignette=PI/4,"
                   f"fade=t=in:st=0:d=0.6,fade=t=out:st={total - 0.8:.2f}:d=0.8,ass={ass.name}[vout]")
    filtros.append(f"[{n}:a]apad=pad_dur=1.2,volume=1.6[voz]")
    filtros.append(f"[{n + 1}:a]lowpass=f=350,volume=0.5[amb]")
    filtros.append("[voz][amb]amix=inputs=2:duration=first:dropout_transition=0,volume=1.8[aout]")
    cmd += ["-filter_complex", ";".join(filtros), "-map", "[vout]", "-map", "[aout]",
            "-t", f"{total:.2f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(salida)]
    correr(cmd, cwd=TMP)


def main():
    SAL.mkdir(exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    hoy = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4))).strftime("%Y-%m-%d")

    if PRUEBA:
        tema = "Prueba local"
        g = {"titulo": "Prueba local", "descripcion": "Prueba", "hashtags": ["#prueba"],
             "narracion": "¿Tú has oído hablar de la ciguapa? Cuentan los viejos que de noche, por la orilla del río, "
                          "se ven unas huellas que van al revés. Quien las sigue, no vuelve igual. ¿Tú crees en eso?",
             "escenas": ["a", "b", "c", "d"]}
        imagenes = [imagen_de_relleno(i) for i in range(4)]
        mp3 = TMP / "voz.mp3"
        correr(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=12",
                "-c:a", "libmp3lame", str(mp3)])
        palabras = []
    else:
        tema = escoger_tema()
        print(f"Tema de hoy: {tema}")
        g = pedir_guion(tema)
        mp3, palabras = narrar(g["narracion"])
        imagenes = bajar_imagenes(g["escenas"][:6])
        while len(imagenes) < 4:  # si Pollinations falla, se completa con fondos oscuros
            imagenes.append(imagen_de_relleno(len(imagenes)))

    ass = subtitulos(palabras, g["narracion"], duracion(mp3))
    video = SAL / "video.mp4"
    armar_video(imagenes, mp3, ass, video)

    tags = " ".join(h if h.startswith("#") else "#" + h for h in g.get("hashtags", []))
    if "#leyendasdominicanas" not in tags:
        tags = "#leyendasdominicanas " + tags
    (SAL / "descripcion.txt").write_text(f"{g['titulo']}\n\n{g.get('descripcion', '')}\n\n{tags}\n", encoding="utf-8")
    (SAL / "guion.txt").write_text(g["narracion"] + "\n", encoding="utf-8")
    if not PRUEBA:
        with open(RAIZ / "registro.txt", "a", encoding="utf-8") as f:
            f.write(f"{hoy} | {tema} | {g['titulo']}\n")
    print(f"Listo: {video} ({duracion(video):.1f} s)")


if __name__ == "__main__":
    main()
