import html
import json
import os
import re
import sys
import unicodedata
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
# "palabras": como lo escribe la gente en los comentarios (minuscula, sin tildes)
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
MAX_COMENTARIOS_POR_CANAL = 20
DIAS_HACIA_ATRAS = 7
DIAS_CUENTA_NUEVA = 30
MINIMO_COMENTARIOS = 50
MINIMO_CANALES = 5


def llamar_youtube(endpoint, parametros):
    parametros["key"] = API_KEY
    url = "https://www.googleapis.com/youtube/v3/" + endpoint + "?" + urllib.parse.urlencode(parametros)
    with urllib.request.urlopen(url, timeout=30) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9 ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


# Informacion de canales (pais y fecha de creacion), guardada para no repetir consultas
info_canales = {}


def cargar_canales(ids):
    faltan = list({i for i in ids if i and i.startswith("UC") and i not in info_canales})
    for inicio in range(0, len(faltan), 50):
        grupo = faltan[inicio:inicio + 50]
        try:
            datos = llamar_youtube("channels", {"part": "snippet", "id": ",".join(grupo), "maxResults": 50})
        except Exception as e:
            print(f"  No se pudo consultar informacion de canales ({e})")
            datos = {}
        for item in datos.get("items", []):
            sn = item.get("snippet", {})
            creado = None
            if sn.get("publishedAt"):
                try:
                    creado = datetime.strptime(sn["publishedAt"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    creado = None
            info_canales[item["id"]] = {"pais": sn.get("country"), "creado": creado}
        for i in grupo:
            info_canales.setdefault(i, {"pais": None, "creado": None})


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
        sn = item["snippet"]
        videos.append((
            item["id"]["videoId"],
            sn.get("channelId", ""),
            html.unescape(sn.get("channelTitle", "Canal desconocido")),
        ))
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
            sn = c["snippet"]
            autor = sn.get("authorChannelId", {}).get("value") or ("nombre:" + sn.get("authorDisplayName", ""))
            comentarios.append((c["id"], sn.get("textDisplay", ""), autor))
        pagina = datos.get("nextPageToken")
        if not pagina:
            break
    return comentarios[:COMENTARIOS_POR_VIDEO]


analyzer = create_analyzer(task="sentiment", lang="es")
resultados = {p: {"POS": 0, "NEG": 0, "NEU": 0} for p in POLITICOS}
detalle = {}
ya_analizados = {}
limite_cuenta_nueva = datetime.now(timezone.utc) - timedelta(days=DIAS_CUENTA_NUEVA)

for nombre, config in POLITICOS.items():
    print(f"Buscando videos de {config['busqueda']}...")
    try:
        videos = buscar_videos(config["busqueda"])
    except Exception as e:
        print(f"  Error al buscar videos: {e}")
        continue

    videos_descartados = {"canal_extranjero": 0, "canal_oficial": 0}
    descartes = {"mismo_autor": 0, "texto_repetido": 0, "cuenta_nueva": 0, "tope_canal": 0}

    # 1) Filtrar videos de canales extranjeros u oficiales del dirigente
    cargar_canales([v[1] for v in videos])
    busqueda_norm = normalizar(config["busqueda"])
    validos = []
    for video_id, canal_id, canal in videos:
        pais = info_canales.get(canal_id, {}).get("pais")
        if pais and pais != "AR":
            videos_descartados["canal_extranjero"] += 1
            print(f"    (descartado canal extranjero: {canal}, {pais})")
            continue
        if busqueda_norm in normalizar(canal):
            videos_descartados["canal_oficial"] += 1
            print(f"    (descartado canal oficial: {canal})")
            continue
        validos.append((video_id, canal))

    # 2) Juntar comentarios que lo mencionan, sin autores ni textos repetidos
    candidatos = {}
    vistos_cid, vistos_autor, vistos_texto = set(), set(), set()
    for video_id, canal in validos:
        for cid, texto, autor in leer_comentarios(video_id):
            if cid in vistos_cid:
                continue
            vistos_cid.add(cid)
            norm = normalizar(texto)
            if not any(palabra in norm for palabra in config["palabras"]):
                continue
            if autor in vistos_autor:
                descartes["mismo_autor"] += 1
                continue
            if norm in vistos_texto:
                descartes["texto_repetido"] += 1
                continue
            vistos_autor.add(autor)
            vistos_texto.add(norm)
            candidatos.setdefault(canal, []).append((cid, texto, autor))

    # 3) Revisar antiguedad de las cuentas y aplicar tope por canal
    cargar_canales([autor for lista in candidatos.values() for _, _, autor in lista])
    canales = {}
    contados = 0
    for canal, lista in candidatos.items():
        aceptados = []
        for cid, texto, autor in lista:
            creado = info_canales.get(autor, {}).get("creado")
            if creado and creado > limite_cuenta_nueva:
                descartes["cuenta_nueva"] += 1
                continue
            if len(aceptados) >= MAX_COMENTARIOS_POR_CANAL:
                descartes["tope_canal"] += 1
                continue
            aceptados.append((cid, texto))
        for cid, texto in aceptados:
            if cid not in ya_analizados:
                ya_analizados[cid] = analyzer.predict(texto[:500]).output
            resultados[nombre][ya_analizados[cid]] += 1
        if aceptados:
            canales[canal] = len(aceptados)
            contados += len(aceptados)

    canales_ordenados = dict(sorted(canales.items(), key=lambda x: -x[1]))
    pocos_datos = contados < MINIMO_COMENTARIOS or len(canales) < MINIMO_CANALES

    print(f"  {len(validos)} videos validos, {contados} comentarios de {len(canales)} canales")
    print(f"  Descartados: {descartes}")
    if pocos_datos:
        print("  AVISO: pocos datos, resultado poco confiable")
    for canal, cantidad in canales_ordenados.items():
        print(f"    - {canal}: {cantidad}")

    detalle[nombre] = {
        "videos": len(validos),
        "comentarios": contados,
        "pocos_datos": pocos_datos,
        "canales": canales_ordenados,
        "videos_descartados": videos_descartados,
        "comentarios_descartados": descartes,
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
    "filtros": {
        "tope_por_canal": MAX_COMENTARIOS_POR_CANAL,
        "un_comentario_por_persona": True,
        "sin_textos_repetidos": True,
        "cuentas_nuevas_excluidas_dias": DIAS_CUENTA_NUEVA,
        "sin_canales_extranjeros_ni_oficiales": True,
    },
    "minimo_confiable": {"comentarios": MINIMO_COMENTARIOS, "canales": MINIMO_CANALES},
    "total_comentarios": total,
    "detalle": detalle,
}
with open("info.json", "w", encoding="utf-8") as f:
    json.dump(info, f, ensure_ascii=False, indent=2)

print(f"Listo: {total} comentarios analizados. Datos guardados en datos.json e info.json")
