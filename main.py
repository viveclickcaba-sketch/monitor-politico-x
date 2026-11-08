import html
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from pysentimiento import create_analyzer

API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    print("ERROR: falta la clave YOUTUBE_API_KEY en los secretos de GitHub.")
    sys.exit(1)

# ============================================================
# LISTA DE POLITICOS A MONITOREAR
# "busqueda": lo que se busca en YouTube
# "palabras": como lo escribe la gente en los comentarios (en minuscula)
# ============================================================
POLITICOS = {
    "Milei":    {"busqueda": "Javier Milei",       "palabras": ["milei"]},
    "Massa":    {"busqueda": "Sergio Massa",       "palabras": ["massa"]},
    "Kicillof": {"busqueda": "Axel Kicillof",      "palabras": ["kicillof", "kiciloff", "kicilof", "axel"]},
    "Macri":    {"busqueda": "Mauricio Macri",     "palabras": ["macri"]},
    "Bullrich": {"busqueda": "Patricia Bullrich",  "palabras": ["bullrich", "patricia"]},
    "Cristina": {"busqueda": "Cristina Kirchner",  "palabras": ["cristina", "cfk", "kirchner"]},
    "Grabois":  {"busqueda": "Juan Grabois",       "palabras": ["grabois"]},
    "Bregman":  {"busqueda": "Myriam Bregman",     "palabras": ["bregman", "myriam"]},
}

# ============================================================
# CONFIGURACION
# ============================================================
VIDEOS_POR_POLITICO = 25
COMENTARIOS_POR_VIDEO = 300
MAX_COMENTARIOS_POR_CANAL = 30
DIAS_HACIA_ATRAS = 7


def llamar_youtube(endpoint, parametros):
    parametros["key"] = API_KEY
    url = "https://www.googleapis.com/youtube/v3/" + endpoint + "?" + urllib.parse.urlencode(parametros)
    with urllib.request.urlopen(url, timeout=30) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def buscar_videos(busqueda):
    desde = (datetime.now(timezone.utc) - timedelta(days=DIAS_HACIA_ATRAS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    datos = llamar_youtube("search", {
        "part": "snippet",
        "q": busqueda,
        "type": "video",
        "order": "relevance",
        "publishedAfter": desde,
        "regionCode": "AR",
        "relevanceLanguage": "es",
        "maxResults": VIDEOS_POR_POLITICO,
    })
    videos = []
    for item in datos.get("items", []):
        video_id = item["id"]["videoId"]
        canal = html.unescape(item["snippet"].get("channelTitle", "Canal desconocido"))
        videos.append((video_id, canal))
    return videos


def leer_comentarios(video_id):
    comentarios = []
    pagina = None
    while len(comentarios) < COMENTARIOS_POR_VIDEO:
        parametros = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": 100,
            "order": "relevance",
            "textFormat": "plainText",
        }
        if pagina:
            parametros["pageToken"] = pagina
        try:
            datos = llamar_youtube("commentThreads", parametros)
        except Exception as e:
            if not comentarios:
                print(f"  Video {video_id}: comentarios no disponibles ({e})")
            break
        for item in datos.get("items", []):
            c = item["snippet"]["topLevelComment"]
            comentarios.append((c["id"], c["snippet"]["textDisplay"]))
        pagina = datos.get("nextPageToken")
        if not pagina:
            break
    return comentarios[:COMENTARIOS_POR_VIDEO]


analyzer = create_analyzer(task="sentiment", lang="es")
resultados = {p: {"POS": 0, "NEG": 0, "NEU": 0} for p in POLITICOS}
detalle = {}
ya_analizados = {}

for nombre, config in POLITICOS.items():
    print(f"Buscando videos de {config['busqueda']}...")
    try:
        videos = buscar_videos(config["busqueda"])
    except Exception as e:
        print(f"  Error al buscar videos: {e}")
        continue

    # Juntar comentarios que mencionan al politico, con tope por canal
    por_canal = {}
    vistos = set()
    for video_id, canal in videos:
        for cid, texto in leer_comentarios(video_id):
            if cid in vistos:
                continue
            texto_min = texto.lower()
            if not any(palabra in texto_min for palabra in config["palabras"]):
                continue
            lista = por_canal.setdefault(canal, [])
            if len(lista) >= MAX_COMENTARIOS_POR_CANAL:
                continue
            lista.append((cid, texto))
            vistos.add(cid)

    # Analizar sentimiento
    canales = {}
    contados = 0
    for canal, lista in por_canal.items():
        for cid, texto in lista:
            if cid not in ya_analizados:
                ya_analizados[cid] = analyzer.predict(texto[:500]).output
            resultados[nombre][ya_analizados[cid]] += 1
        canales[canal] = len(lista)
        contados += len(lista)

    canales_ordenados = dict(sorted(canales.items(), key=lambda x: -x[1]))
    print(f"  {len(videos)} videos, {contados} comentarios de {len(canales)} canales")
    for canal, cantidad in canales_ordenados.items():
        print(f"    - {canal}: {cantidad}")

    detalle[nombre] = {
        "videos": len(videos),
        "comentarios": contados,
        "canales": canales_ordenados,
    }

total = sum(sum(v.values()) for v in resultados.values())
if total == 0:
    print("ERROR: no se pudo analizar ningun comentario. No se actualizan los datos.")
    sys.exit(1)

with open("datos.json", "w", encoding="utf-8") as f:
    json.dump(resultados, f, ensure_ascii=False, indent=2)

hora_ar = datetime.now(timezone(timedelta(hours=-3)))
info = {
    "actualizado": hora_ar.strftime("%d/%m/%Y %H:%M"),
    "fuente": "Comentarios de YouTube",
    "periodo": f"Videos de los ultimos {DIAS_HACIA_ATRAS} dias",
    "tope_por_canal": MAX_COMENTARIOS_POR_CANAL,
    "total_comentarios": total,
    "detalle": detalle,
}
with open("info.json", "w", encoding="utf-8") as f:
    json.dump(info, f, ensure_ascii=False, indent=2)

print(f"Listo: {total} comentarios analizados. Datos guardados en datos.json e info.json")
