#!/usr/bin/env python3
# Manda el video del día a la bandeja de TikTok como BORRADOR (el dueño lo publica desde la app).
#   python3 tiktok_borrador.py conectar <codigo>   -> primera vez: cambia el código por tokens
#   python3 tiktok_borrador.py subir salida/video.mp4
# El token se guarda cifrado en tiktok_token.enc (la llave es el secreto TIKTOK_CLIENT_SECRET).
import json, os, pathlib, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent
ARCHIVO = RAIZ / "tiktok_token.enc"
API = "https://open.tiktokapis.com/v2"
REDIRECT = "https://cheloelmele17.github.io/historias-rd/callback.html"
KEY = os.environ["TIKTOK_CLIENT_KEY"].strip()
SECRET = os.environ["TIKTOK_CLIENT_SECRET"].strip()


def pedir(url, data=None, headers=None, metodo=None, cuerpo=None):
    if data is not None:
        cuerpo = urllib.parse.urlencode(data).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
    req = urllib.request.Request(url, data=cuerpo, headers=headers or {}, method=metodo or ("POST" if cuerpo is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            texto = r.read().decode() or "{}"
            return json.loads(texto)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"TikTok dio error {e.code}: {e.read()[:500]!r}")


def cifrar(texto):
    out = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-a", "-A", "-pass", "env:TIKTOK_CLIENT_SECRET"],
                         input=texto.encode(), capture_output=True, check=True).stdout
    ARCHIVO.write_bytes(out + b"\n")


def descifrar():
    out = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-a", "-A", "-pass", "env:TIKTOK_CLIENT_SECRET"],
                         input=ARCHIVO.read_bytes().strip(), capture_output=True, check=True).stdout
    return out.decode()


def guardar(t):
    if not t.get("refresh_token"):
        raise SystemExit(f"TikTok no devolvió token: {t}")
    cifrar(json.dumps({"refresh_token": t["refresh_token"], "open_id": t.get("open_id", ""), "guardado": int(time.time())}))
    print("Token guardado (cifrado). Vence en", int(t.get("refresh_expires_in", 0)) // 86400, "días")


def conectar(codigo):
    t = pedir(f"{API}/oauth/token/", {"client_key": KEY, "client_secret": SECRET, "code": urllib.parse.unquote(codigo.strip()),
                                       "grant_type": "authorization_code", "redirect_uri": REDIRECT})
    guardar(t)
    print("Conectado. Permisos:", t.get("scope"))


def token_fresco():
    datos = json.loads(descifrar())
    t = pedir(f"{API}/oauth/token/", {"client_key": KEY, "client_secret": SECRET, "grant_type": "refresh_token",
                                       "refresh_token": datos["refresh_token"]})
    if t.get("refresh_token") and t["refresh_token"] != datos["refresh_token"]:
        guardar(t)
    if not t.get("access_token"):
        raise SystemExit(f"No se pudo renovar el permiso de TikTok: {t}")
    return t["access_token"]


def subir(ruta):
    video = pathlib.Path(ruta).read_bytes()
    n = len(video)
    acceso = token_fresco()
    cab = {"Authorization": f"Bearer {acceso}", "Content-Type": "application/json; charset=UTF-8"}
    ini = pedir(f"{API}/post/publish/inbox/video/init/", headers=cab, cuerpo=json.dumps(
        {"source_info": {"source": "FILE_UPLOAD", "video_size": n, "chunk_size": n, "total_chunk_count": 1}}).encode())
    if ini.get("error", {}).get("code") not in (None, "ok"):
        raise SystemExit(f"TikTok rechazó el inicio: {ini['error']}")
    d = ini["data"]
    pedir(d["upload_url"], metodo="PUT", cuerpo=video,
          headers={"Content-Type": "video/mp4", "Content-Length": str(n), "Content-Range": f"bytes 0-{n - 1}/{n}"})
    print("Video subido a TikTok, revisando...")
    estado = ""
    for _ in range(20):
        time.sleep(10)
        s = pedir(f"{API}/post/publish/status/fetch/", headers=cab, cuerpo=json.dumps({"publish_id": d["publish_id"]}).encode())
        estado = s.get("data", {}).get("status", "")
        print("Estado:", estado, s.get("data", {}).get("fail_reason", ""))
        if estado in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE") or estado == "FAILED":
            break
    if estado == "FAILED":
        raise SystemExit("TikTok no aceptó el borrador")
    print("Borrador enviado a la bandeja de TikTok")


if __name__ == "__main__":
    if sys.argv[1] == "conectar":
        conectar(sys.argv[2])
    else:
        subir(sys.argv[2])
