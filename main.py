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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
URL_WEB = "https://viveclickcaba-sketch.github.io/monitor-politico-x/"
METODO = 2

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

# Otras figuras: si un comentario las nombra, no se cuenta
# (no se puede saber a quien va dirigido el tono)
OTROS_NOMBRES = ["caputo", "karina", "adorni", "villarruel", "sturzenegger", "pettovello", "francos", "espert"]

# ============================================================
# CONFIGURACION
# ============================================================
VIDEOS_POR_POLITICO = 25
COMENTARIOS_POR_VIDEO = 300
MAX_COMENTARIOS_POR_CANAL = 20
DIAS_HACIA_ATRAS = 7
DIAS_CUENTA_NUEVA = 30
DIAS_ACUMULADO = 30
MINIMO_COMENTARIOS = 50
MINIMO_CANALES = 5
EJEMPLOS_POR_TIPO = 3
VIDEOS_DESTACADOS = 3
MAX_HISTORIAL = 200
UMBRAL_ALERTA = 15


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


def menciona(texto_norm, palabras):
    return any(re.search(r"\b" + re.escape(p), texto_norm) for p in palabras)


def enviar_telegram(texto):
    datos = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    try:
        urllib.request.urlopen("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage", data=datos, timeout=30)
        print("Aviso enviado por Telegram")
    except Exception as e:
        print(f"No se pudo enviar el aviso por Telegram ({e})")


def leer_json(ruta, por_defecto):
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return por_defecto
    return por_defecto


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
            html.unescape(sn.get("title", "")),
        ))
    return videos


def cantidad_comentarios_videos(ids):
    if not ids:
        return {}
    try:
        datos = llamar_youtube("videos", {"part": "statistics", "id": ",".join(ids[:50])})
    except Exception as e:
        print(f"  No se pudieron consultar estadisticas de videos ({e})")
        return {}
    resultado = {}
    for item in datos.get("items", []):
        try:
            resultado[item["id"]] = int(item.get("statistics", {}).get("commentCount", 0) or 0)
        except ValueError:
            resultado[item["id"]] = 0
    return resultado


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
            likes = sn.get("likeCount", 0) or 0
            comentarios.append((c["id"], sn.get("textDisplay", ""), autor, likes))
        pagina = datos.get("nextPageToken")
        if not pagina:
            break
    return comentarios[:COMENTARIOS_POR_VIDEO]


def porcentaje_negativo(d):
    total = d.get("POS", 0) + d.get("NEG", 0) + d.get("NEU", 0)
    return d.get("NEG", 0) * 100 / total if total else None


analyzer = create_analyzer(task="sentiment", lang="es")
resultados = {p: {"POS": 0, "NEG": 0, "NEU": 0} for p in POLITICOS}
detalle = {}
ya_analizados = {}
ids_por_politico = {p: [] for p in POLITICOS}
limite_cuenta_nueva = datetime.now(timezone.utc) - timedelta(days=DIAS_CUENTA_NUEVA)

for nombre, config in POLITICOS.items():
    print(f"Buscando videos de {config['busqueda']}...")
    try:
        videos = buscar_videos(config["busqueda"])
    except Exception as e:
        print(f"  Error al buscar videos: {e}")
        continue

    videos_descartados = {"canal_extranjero": 0, "canal_oficial": 0}
    descartes = {"menciona_otros": 0, "mismo_autor": 0, "texto_repetido": 0, "cuenta_nueva": 0, "tope_canal": 0}
    otros_politicos = [c["palabras"] for n, c in POLITICOS.items() if n != nombre]

    # 1) Filtrar videos de canales extranjeros u oficiales del dirigente
    cargar_canales([v[1] for v in videos])
    busqueda_norm = normalizar(config["busqueda"])
    validos = []
    for video_id, canal_id, canal, titulo in videos:
        pais = info_canales.get(canal_id, {}).get("pais")
        if pais and pais != "AR":
            videos_descartados["canal_extranjero"] += 1
            print(f"    (descartado canal extranjero: {canal}, {pais})")
            continue
        if busqueda_norm in normalizar(canal):
            videos_descartados["canal_oficial"] += 1
            print(f"    (descartado canal oficial: {canal})")
            continue
        validos.append((video_id, canal, titulo))

    # 2) Videos con mas conversacion
    conteo = cantidad_comentarios_videos([v[0] for v in validos])
    destacados = sorted(validos, key=lambda v: -conteo.get(v[0], 0))[:VIDEOS_DESTACADOS]
    videos_destacados = [{
        "titulo": titulo,
        "canal": canal,
        "url": "https://www.youtube.com/watch?v=" + video_id,
        "comentarios": conteo.get(video_id, 0),
    } for video_id, canal, titulo in destacados]

    # 3) Juntar comentarios que lo nombran SOLO a el, sin autores ni textos repetidos
    candidatos = {}
    vistos_cid, vistos_autor, vistos_texto = set(), set(), set()
    for video_id, canal, titulo in validos:
        for cid, texto, autor, likes in leer_comentarios(video_id):
            if cid in vistos_cid:
                continue
            vistos_cid.add(cid)
            norm = normalizar(texto)
            if not menciona(norm, config["palabras"]):
                continue
            if any(menciona(norm, palabras) for palabras in otros_politicos) or menciona(norm, OTROS_NOMBRES):
                descartes["menciona_otros"] += 1
                continue
            if autor in vistos_autor:
                descartes["mismo_autor"] += 1
                continue
            if norm in vistos_texto:
                descartes["texto_repetido"] += 1
                continue
            vistos_autor.add(autor)
            vistos_texto.add(norm)
            candidatos.setdefault(canal, []).append((cid, texto, autor, likes))

    # 4) Revisar antiguedad de las cuentas, aplicar tope por canal y analizar
    cargar_canales([c[2] for lista in candidatos.values() for c in lista])
    canales = {}
    contados = 0
    analizados_politico = []
    for canal, lista in candidatos.items():
        aceptados = []
        for cid, texto, autor, likes in lista:
            creado = info_canales.get(autor, {}).get("creado")
            if creado and creado > limite_cuenta_nueva:
                descartes["cuenta_nueva"] += 1
                continue
            if len(aceptados) >= MAX_COMENTARIOS_POR_CANAL:
                descartes["tope_canal"] += 1
                continue
            aceptados.append((cid, texto, likes))
        for cid, texto, likes in aceptados:
            if cid not in ya_analizados:
                ya_analizados[cid] = analyzer.predict(texto[:500]).output
            sentimiento = ya_analizados[cid]
            resultados[nombre][sentimiento] += 1
            analizados_politico.append((sentimiento, likes, texto))
            ids_por_politico[nombre].append(cid)
        if aceptados:
            canales[canal] = len(aceptados)
            contados += len(aceptados)

    # 5) Comentarios de ejemplo (los mas votados, sin nombre de autor)
    def ejemplos_de(tipo):
        lista = sorted([a for a in analizados_politico if a[0] == tipo], key=lambda a: -a[1])
        return [{"texto": t[:280], "likes": l} for _, l, t in lista[:EJEMPLOS_POR_TIPO]]

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
        "videos_destacados": videos_destacados,
        "ejemplos": {"positivos": ejemplos_de("POS"), "negativos": ejemplos_de("NEG")},
    }

total = sum(sum(v.values()) for v in resultados.values())
if total == 0:
    print("ERROR: no se pudo analizar ningun comentario. No se actualizan los datos.")
    sys.exit(1)

hora_ar = datetime.now(timezone(timedelta(hours=-3)))
hoy = hora_ar.strftime("%Y-%m-%d")
limite_acum = (hora_ar - timedelta(days=DIAS_ACUMULADO)).strftime("%Y-%m-%d")

# ============================================================
# ACUMULADO: cada comentario cuenta una sola vez (ultimos 30 dias)
# ============================================================
acumulado = leer_json("acumulado.json", {})
for nombre, ids in ids_por_politico.items():
    registro = acumulado.setdefault(nombre, {})
    for cid in ids:
        if cid not in registro:
            registro[cid] = {"s": ya_analizados[cid], "f": hoy}
for nombre in list(acumulado.keys()):
    acumulado[nombre] = {cid: v for cid, v in acumulado[nombre].items() if v.get("f", "") >= limite_acum}

datos_acumulados = {}
for nombre in POLITICOS:
    conteo = {"POS": 0, "NEG": 0, "NEU": 0}
    for v in acumulado.get(nombre, {}).values():
        if v.get("s") in conteo:
            conteo[v["s"]] += 1
    datos_acumulados[nombre] = conteo

with open("acumulado.json", "w", encoding="utf-8") as f:
    json.dump(acumulado, f, ensure_ascii=False)

# ============================================================
# HISTORIAL
# ============================================================
historial = leer_json("historial.json", [])
anterior = historial[-1] if historial else None
historial.append({
    "fecha": hora_ar.strftime("%d/%m %H:%M"),
    "fecha_completa": hora_ar.strftime("%d/%m/%Y %H:%M"),
    "fecha_iso": hoy,
    "metodo": METODO,
    "datos": resultados,
    "pocos_datos": {n: d["pocos_datos"] for n, d in detalle.items()},
})
historial = historial[-MAX_HISTORIAL:]
with open("historial.json", "w", encoding="utf-8") as f:
    json.dump(historial, f, ensure_ascii=False, indent=2)

corridas_acumuladas = sum(1 for h in historial if h.get("metodo") == METODO and h.get("fecha_iso", "") >= limite_acum)

# ============================================================
# DATOS DE ESTA CORRIDA E INFO GENERAL
# ============================================================
with open("datos.json", "w", encoding="utf-8") as f:
    json.dump(resultados, f, ensure_ascii=False, indent=2)

info = {
    "actualizado": hora_ar.strftime("%d/%m/%Y %H:%M"),
    "metodo": METODO,
    "fuente": "Comentarios de YouTube",
    "periodo": f"Videos de los ultimos {DIAS_HACIA_ATRAS} dias",
    "filtros": {
        "solo_un_dirigente_por_comentario": True,
        "otros_nombres_excluidos": OTROS_NOMBRES,
        "tope_por_canal": MAX_COMENTARIOS_POR_CANAL,
        "un_comentario_por_persona": True,
        "sin_textos_repetidos": True,
        "cuentas_nuevas_excluidas_dias": DIAS_CUENTA_NUEVA,
        "sin_canales_extranjeros_ni_oficiales": True,
    },
    "minimo_confiable": {"comentarios": MINIMO_COMENTARIOS, "canales": MINIMO_CANALES},
    "total_comentarios": total,
    "acumulado": {
        "dias": DIAS_ACUMULADO,
        "corridas": corridas_acumuladas,
        "datos": datos_acumulados,
        "pocos_datos": {n: sum(d.values()) < MINIMO_COMENTARIOS for n, d in datos_acumulados.items()},
    },
    "detalle": detalle,
}
with open("info.json", "w", encoding="utf-8") as f:
    json.dump(info, f, ensure_ascii=False, indent=2)

# ============================================================
# AVISO POR TELEGRAM SI HAY CAMBIOS FUERTES
# ============================================================
cambios = []
if anterior and anterior.get("metodo") == METODO:
    for nombre in resultados:
        previo = anterior.get("datos", {}).get(nombre)
        if not previo:
            continue
        if detalle.get(nombre, {}).get("pocos_datos") or anterior.get("pocos_datos", {}).get(nombre):
            continue
        antes = porcentaje_negativo(previo)
        ahora = porcentaje_negativo(resultados[nombre])
        if antes is None or ahora is None:
            continue
        diferencia = ahora - antes
        if abs(diferencia) >= UMBRAL_ALERTA:
            verbo = "subió" if diferencia > 0 else "bajó"
            cambios.append(f"• {nombre}: el negativo {verbo} de {antes:.0f}% a {ahora:.0f}% ({diferencia:+.0f} puntos)")

if cambios:
    print("Cambios fuertes detectados:")
    for c in cambios:
        print("  " + c)
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        mensaje = "📊 Monitor Político: cambios fuertes\n\n" + "\n".join(cambios) + f"\n\nActualizado: {info['actualizado']}\n{URL_WEB}"
        enviar_telegram(mensaje)
    else:
        print("(Telegram no configurado, no se envia aviso)")
else:
    print("Sin cambios fuertes respecto de la corrida anterior")

print(f"Listo: {total} comentarios en esta corrida. Acumulado de {corridas_acumuladas} corrida(s) con el metodo nuevo.")
