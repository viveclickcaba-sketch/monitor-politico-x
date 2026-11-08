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
    "Milei":    {"busqueda": "Javier Milei",      "palabras": ["milei"]},
    "Massa":    {"busqueda": "Sergio Massa",      "palabras": ["massa"]},
    "Kicillof": {"busqueda": "Axel Kicillof",     "palabras": ["kicillof", "kiciloff", "kicilof"]},
    "Macri":    {"busqueda": "Mauricio Macri",    "palabras": ["macri"]},
    "Bullrich": {"busqueda": "Patricia Bullrich", "palabras": ["bullrich"]},
}

VIDEOS_POR_POLITICO = 10
COMENTARIOS_POR_VIDEO = 100
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
    return [item["id"]["videoId"] for item in datos.get("items", [])]


def leer_comentarios(video_id):
    try:
        datos = llamar_youtube("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": COMENTARIOS_POR_VIDEO,
            "order": "relevance",
            "textFormat": "plainText",
        })
    except Exception as e:
        print(f"  Video {video_id}: comentarios no disponibles ({e})")
        return []
    comentarios = []
    for item in datos.get("items", []):
        c = item["snippet"]["topLevelComment"]
        comentarios.append((c["id"], c["snippet"]["textDisplay"]))
    return comentarios


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

    contados = 0
    for video_id in videos:
        for cid, texto in leer_comentarios(video_id):
            texto_min = texto.lower()
            if not any(palabra in texto_min for palabra in config["palabras"]):
                continue
            if cid not in ya_analizados:
                ya_analizados[cid] = analyzer.predict(texto[:500]).output
            resultados[nombre][ya_analizados[cid]] += 1
            contados += 1

    print(f"  {len(videos)} videos, {contados} comentarios que lo mencionan")
    detalle[nombre] = {"videos": len(videos), "comentarios": contados}

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
    "total_comentarios": total,
    "detalle": detalle,
}
with open("info.json", "w", encoding="utf-8") as f:
    json.dump(info, f, ensure_ascii=False, indent=2)

print(f"Listo: {total} comentarios analizados. Datos guardados en datos.json e info.json")
