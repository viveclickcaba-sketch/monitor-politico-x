import gc
import html
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

from pysentimiento import create_analyzer

API_KEY = os.getenv("YOUTUBE_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PAIS_ELEGIDO = os.getenv("PAIS") or "Todos"
URL_WEB = "https://viveclickcaba-sketch.github.io/monitor-politico-x/"
CARPETA = "datos"
METODO = 3

if not API_KEY:
    print("ERROR: falta la clave YOUTUBE_API_KEY en los secretos de GitHub.")
    sys.exit(1)

# ============================================================
# PAISES Y DIRIGENTES
# "busqueda": lo que se busca en YouTube
# "palabras": como lo escribe la gente (minuscula, sin tildes)
#   - una palabra normal tambien detecta derivados (ej. "milei" -> "mileista")
#   - si empieza con "=" se detecta solo la palabra exacta (ej. "=petro" no cuenta "petroleo")
#   - si empieza con "~" se busca tal cual, respetando la ñ (ej. "~peña" no cuenta "pena")
# "otros": figuras que, si aparecen en el comentario, hacen que no se cuente
# "dias" (opcional): cuantos dias hacia atras mirar (por defecto 7)
# ============================================================
PAISES = {
    "ar": {
        "nombre": "Argentina", "idioma": "es", "region": "AR", "videos": 25, "paginas": 3,
        "politicos": {
            "Milei":    {"busqueda": "Javier Milei",      "palabras": ["milei"]},
            "Massa":    {"busqueda": "Sergio Massa",      "palabras": ["massa"]},
            "Kicillof": {"busqueda": "Axel Kicillof",     "palabras": ["kicillof", "kiciloff", "kicilof", "axel"]},
            "Macri":    {"busqueda": "Mauricio Macri",    "palabras": ["macri"]},
            "Bullrich": {"busqueda": "Patricia Bullrich", "palabras": ["bullrich", "patricia"]},
            "Cristina": {"busqueda": "Cristina Kirchner", "palabras": ["cristina", "cfk", "kirchner"]},
            "Grabois":  {"busqueda": "Juan Grabois",      "palabras": ["grabois"]},
            "Bregman":  {"busqueda": "Myriam Bregman",    "palabras": ["bregman", "myriam"]},
        },
        "otros": ["caputo", "karina", "adorni", "villarruel", "sturzenegger", "pettovello", "francos", "espert"],
    },
    "es": {
        "nombre": "España", "idioma": "es", "region": "ES", "videos": 20, "paginas": 2,
        "politicos": {
            "Sánchez":       {"busqueda": "Pedro Sánchez",          "palabras": ["sanchez", "sanxe"]},
            "Feijóo":        {"busqueda": "Alberto Núñez Feijóo",   "palabras": ["feijoo", "feijo"]},
            "Abascal":       {"busqueda": "Santiago Abascal",       "palabras": ["abascal"]},
            "Colau":         {"busqueda": "Ada Colau",              "palabras": ["colau"]},
            "Irene Montero": {"busqueda": "Irene Montero",          "palabras": ["irene montero"]},
            "Rufián":        {"busqueda": "Gabriel Rufián",         "palabras": ["=rufian"]},
        },
        "otros": ["ayuso", "puigdemont", "yolanda diaz", "belarra", "illa"],
    },
    "co": {
        "nombre": "Colombia", "idioma": "es", "region": "CO", "videos": 20, "paginas": 2,
        "politicos": {
            "De la Espriella": {"busqueda": "Abelardo de la Espriella", "palabras": ["espriella", "abelardo"]},
            "Cepeda":          {"busqueda": "Iván Cepeda",              "palabras": ["cepeda"]},
            "Petro":           {"busqueda": "Gustavo Petro",            "palabras": ["=petro"]},
            "Uribe":           {"busqueda": "Álvaro Uribe",             "palabras": ["uribe"]},
            "Fajardo":         {"busqueda": "Sergio Fajardo",           "palabras": ["fajardo"]},
        },
        "otros": ["paloma valencia", "vicky davila", "claudia lopez", "benedetti", "francia marquez"],
    },
    "us": {
        "nombre": "Estados Unidos", "idioma": "en", "region": "US", "videos": 20, "paginas": 2,
        "politicos": {
            "Trump":    {"busqueda": "Donald Trump",               "palabras": ["trump"]},
            "Vance":    {"busqueda": "JD Vance",                   "palabras": ["=vance"]},
            "Rubio":    {"busqueda": "Marco Rubio",                "palabras": ["=rubio"]},
            "Newsom":   {"busqueda": "Gavin Newsom",               "palabras": ["newsom"]},
            "AOC":      {"busqueda": "Alexandria Ocasio-Cortez",   "palabras": ["=aoc", "ocasio"]},
            "Jeffries": {"busqueda": "Hakeem Jeffries",            "palabras": ["jeffries"]},
        },
        "otros": ["biden", "obama", "harris", "musk", "mamdani", "schumer", "hegseth"],
    },
    "br": {
        "nombre": "Brasil", "idioma": "pt", "region": "BR", "videos": 20, "paginas": 2,
        "politicos": {
            "Lula":             {"busqueda": "Lula",                "palabras": ["=lula"]},
            "Flávio Bolsonaro": {"busqueda": "Flávio Bolsonaro",    "palabras": ["flavio"]},
            "Jair Bolsonaro":   {"busqueda": "Jair Bolsonaro",      "palabras": ["=jair"]},
            "Tarcísio":         {"busqueda": "Tarcísio de Freitas", "palabras": ["tarcisio"]},
            "Haddad":           {"busqueda": "Fernando Haddad",     "palabras": ["haddad"]},
        },
        "otros": ["michelle", "moraes", "eduardo bolsonaro", "alckmin", "ciro gomes"],
    },
    "it": {
        "nombre": "Italia", "idioma": "it", "region": "IT", "videos": 20, "paginas": 2,
        "politicos": {
            "Meloni":  {"busqueda": "Giorgia Meloni",   "palabras": ["meloni"]},
            "Salvini": {"busqueda": "Matteo Salvini",   "palabras": ["salvini"]},
            "Tajani":  {"busqueda": "Antonio Tajani",   "palabras": ["tajani"]},
            "Schlein": {"busqueda": "Elly Schlein",     "palabras": ["schlein"]},
            "Conte":   {"busqueda": "Giuseppe Conte",   "palabras": ["=conte"]},
        },
        "otros": ["renzi", "calenda", "vannacci", "draghi", "mattarella"],
    },
    "py": {
        "nombre": "Paraguay", "idioma": "es", "region": "PY", "videos": 25, "paginas": 3, "dias": 14,
        "politicos": {
            "Santiago Peña": {"busqueda": "Santiago Peña",      "palabras": ["santiago pena", "santi pena", "presidente pena", "~peña"]},
            "Cartes":        {"busqueda": "Horacio Cartes",     "palabras": ["cartes"]},
            "Efraín Alegre": {"busqueda": "Efraín Alegre",      "palabras": ["efrain", "=alegre"]},
            "Payo Cubas":    {"busqueda": "Payo Cubas",         "palabras": ["=payo", "cubas"]},
            "Mario Abdo":    {"busqueda": "Mario Abdo Benítez", "palabras": ["=abdo", "marito"]},
        },
        "otros": ["lugo", "nakayama", "velazquez"],
    },
    "ve": {
        "nombre": "Venezuela", "idioma": "es", "region": "VE", "videos": 20, "paginas": 2,
        "politicos": {
            "Delcy Rodríguez":      {"busqueda": "Delcy Rodríguez",      "palabras": ["delcy"]},
            "María Corina Machado": {"busqueda": "María Corina Machado", "palabras": ["machado", "maria corina", "=mcm"]},
            "Edmundo González":     {"busqueda": "Edmundo González",     "palabras": ["edmundo"]},
            "Maduro":               {"busqueda": "Nicolás Maduro",       "palabras": ["=maduro"]},
            "Diosdado Cabello":     {"busqueda": "Diosdado Cabello",     "palabras": ["diosdado"]},
        },
        "otros": ["jorge rodriguez", "padrino", "capriles", "guaido"],
    },
}

# ============================================================
# CONFIGURACION GENERAL
# ============================================================
MAX_COMENTARIOS_POR_CANAL = 20
DIAS_HACIA_ATRAS = 7
DIAS_CUENTA_NUEVA = 30
DIAS_ACUMULADO = 30
MINIMO_COMENTARIOS = 50
MINIMO_CANALES = 5
EJEMPLOS_POR_TIPO = 3
VIDEOS_DESTACADOS = 3
TEMAS_POR_DIRIGENTE = 12
MAX_HISTORIAL = 200
UMBRAL_ALERTA = 15
EXCLUIR_IRONIA = True
# El detector de ironia solo se usa donde funciona bien (en portugues marcaba todo como ironico)
IDIOMAS_CON_IRONIA = {"es"}

EMOCIONES = {
    "joy": "alegria", "sadness": "tristeza", "anger": "enojo", "surprise": "sorpresa",
    "disgust": "asco", "fear": "miedo", "others": "sin_emocion_clara",
}
TONOS = ("POS", "NEG", "NEU")

STOPWORDS = {
    "es": set("""
de la que el en y a los se del las un por con no una su para es al lo como mas pero sus le ya o
este si porque esta entre cuando muy sin sobre tambien me hasta hay donde quien desde todo nos
durante todos uno les ni contra otros ese eso ante ellos esto mi antes algunos unos yo otro otras
otra tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo nosotros
mis tu te ti tus ellas vos ustedes usted mio mia suyo nuestro nuestra esos esas estoy estamos estan
ser son fue era eran sera seria hace hacer tiene tienen tener tengo han hay solo asi aca ahi alla
bien mal van vamos dice dijo porq jaja jajaja jajajaja jajajajaja gente pais argentina argentinos
toda todas cada siempre nunca ahora dia dias anos vez cosa cosas puede pueden menos igual mismo
misma lado parte decir sabe saben hacen hizo creo aqui alli despues entonces mejor peor pues digo
quiere quieren estaba estaban tenia habia sido sean esten queda quedan espana colombia paraguay venezuela
""".split()),
    "en": set("""
the a an and or but if of to in on at for with by from as is are was were be been being it its this
that these those he she they them his her their we you your i me my our not no so do does did have
has had will would can could just about what who how why when there here than then also more most
very all any some one out up get got like dont im thats people america american americans going know
""".split()),
    "pt": set("""
de a o que e do da em um para com nao uma os no se na por mais as dos como mas foi ao ele das tem seu
sua ou ser quando muito nos ja esta eu tambem so pelo pela ate isso ela entre depois sem mesmo aos
seus quem nas me esse eles voce essa num nem suas meu minha numa pelos elas qual lhe deles essas esses
pelas este dele tu te voces dela isto aquilo vai pra pro kkk kkkk kkkkk kkkkkk gente brasil povo aqui
sim agora sobre tudo todo todos brasileiro brasileiros
""".split()),
    "it": set("""
di a da in con su per tra fra il lo la i gli le un uno una e ed o ma se che non come anche piu del
della dei delle al alla ai alle nel nella sono era stato essere ha hanno ho questo questa quello
quella ci si mi ti vi lui lei loro noi voi io tu tutto tutti molto poco cosa chi dove quando perche
gia ancora solo sempre mai qui ora fare fa dice detto italia italiani gente
""".split()),
}


# ============================================================
# UTILIDADES
# ============================================================
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


def menciona(texto_norm, palabras, texto_crudo=""):
    crudo = unicodedata.normalize("NFC", texto_crudo.lower()) if texto_crudo else ""
    for p in palabras:
        if p.startswith("~"):
            if crudo and re.search(r"(?<!\w)" + re.escape(p[1:]), crudo):
                return True
        elif p.startswith("="):
            if re.search(r"\b" + re.escape(p[1:]) + r"\b", texto_norm):
                return True
        elif re.search(r"\b" + re.escape(p), texto_norm):
            return True
    return False


def etiqueta(salida, validas, por_defecto):
    """Toma la salida de un modelo (texto o lista) y devuelve una etiqueta valida."""
    if isinstance(salida, (list, tuple)):
        salida = salida[0] if salida else por_defecto
    return salida if salida in validas else por_defecto


def leer_json(ruta, por_defecto):
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return por_defecto
    return por_defecto


def guardar_json(ruta, datos, indent=2):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=indent)


def a_entero(valor):
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


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


def porcentaje_negativo(d):
    total = d.get("POS", 0) + d.get("NEG", 0) + d.get("NEU", 0)
    return d.get("NEG", 0) * 100 / total if total else None


# ============================================================
# MODELOS DE ANALISIS (se cargan por idioma y se liberan al cambiar)
# ============================================================
modelos = {"idioma": None}


def cargar_modelo(tarea, idioma):
    try:
        return create_analyzer(task=tarea, lang=idioma)
    except Exception as e:
        print(f"  No se pudo cargar el modelo de {tarea} en '{idioma}' ({e}). Se sigue sin esa variable.")
        return None


def modelos_para(idioma):
    if modelos.get("idioma") == idioma:
        return modelos
    if modelos.get("idioma") is not None:
        modelos.clear()
        gc.collect()
        cache = os.path.expanduser("~/.cache/huggingface")
        shutil.rmtree(cache, ignore_errors=True)
    print(f"Cargando modelos de analisis en idioma '{idioma}'...")
    modelos["idioma"] = idioma
    modelos["sentimiento"] = cargar_modelo("sentiment", idioma)
    modelos["emocion"] = cargar_modelo("emotion", idioma)
    modelos["odio"] = cargar_modelo("hate_speech", idioma)
    if idioma in IDIOMAS_CON_IRONIA:
        modelos["ironia"] = cargar_modelo("irony", idioma)
    else:
        print(f"  (Detector de ironia desactivado para '{idioma}')")
        modelos["ironia"] = None
    return modelos


def analizar(texto, m):
    t = texto[:500]
    r = {"i": False}
    if m.get("ironia"):
        try:
            r["i"] = etiqueta(m["ironia"].predict(t).output, ("ironic", "not ironic"), "not ironic") == "ironic"
        except Exception:
            r["i"] = False
    if r["i"] and EXCLUIR_IRONIA:
        return r
    r["s"] = etiqueta(m["sentimiento"].predict(t).output, TONOS, "NEU")
    r["e"] = "others"
    if m.get("emocion"):
        try:
            r["e"] = etiqueta(m["emocion"].predict(t).output, tuple(EMOCIONES.keys()), "others")
        except Exception:
            r["e"] = "others"
    r["a"] = False
    if m.get("odio"):
        try:
            salida = m["odio"].predict(t).output
            salida = salida if isinstance(salida, (list, tuple)) else [salida]
            r["a"] = any(x in ("aggressive", "hateful") for x in salida)
        except Exception:
            r["a"] = False
    return r


# ============================================================
# YOUTUBE
# ============================================================
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


def buscar_videos(busqueda, region, idioma, cantidad, dias):
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")
    datos = llamar_youtube("search", {
        "part": "snippet",
        "q": busqueda,
        "type": "video",
        "order": "relevance",
        "publishedAfter": desde,
        "regionCode": region,
        "relevanceLanguage": idioma,
        "maxResults": cantidad,
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


def estadisticas_videos(ids):
    if not ids:
        return {}
    try:
        datos = llamar_youtube("videos", {"part": "statistics", "id": ",".join(ids[:50])})
    except Exception as e:
        print(f"  No se pudieron consultar estadisticas de videos ({e})")
        return {}
    resultado = {}
    for item in datos.get("items", []):
        st = item.get("statistics", {})
        resultado[item["id"]] = {
            "comentarios": a_entero(st.get("commentCount")),
            "vistas": a_entero(st.get("viewCount")),
            "likes": a_entero(st.get("likeCount")),
        }
    return resultado


def leer_comentarios(video_id, maximo):
    comentarios = []
    pagina = None
    while len(comentarios) < maximo:
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
            hilo = item["snippet"]
            c = hilo["topLevelComment"]
            sn = c["snippet"]
            autor = sn.get("authorChannelId", {}).get("value") or ("nombre:" + sn.get("authorDisplayName", ""))
            comentarios.append((c["id"], sn.get("textDisplay", ""), autor,
                                a_entero(sn.get("likeCount")), a_entero(hilo.get("totalReplyCount"))))
        pagina = datos.get("nextPageToken")
        if not pagina:
            break
    return comentarios[:maximo]


# ============================================================
# PROCESAR UN PAIS
# ============================================================
def ruta(codigo, archivo):
    return os.path.join(CARPETA, codigo, archivo)


def procesar_pais(codigo, cfg):
    print("")
    print("=" * 60)
    print(f"PAIS: {cfg['nombre']} ({codigo})")
    print("=" * 60)
    os.makedirs(os.path.join(CARPETA, codigo), exist_ok=True)

    if codigo == "ar":
        for archivo in ("historial.json", "acumulado.json"):
            if not os.path.exists(ruta("ar", archivo)) and os.path.exists(archivo):
                shutil.copy(archivo, ruta("ar", archivo))

    m = modelos_para(cfg["idioma"])
    if not m.get("sentimiento"):
        print("  No hay modelo de tono para este idioma. Se saltea el pais.")
        return False

    dias = cfg.get("dias", DIAS_HACIA_ATRAS)
    politicos = cfg["politicos"]
    otros_nombres = cfg.get("otros", [])
    stop = STOPWORDS.get(cfg["idioma"], set())
    excluir_temas = set()
    for o in otros_nombres:
        excluir_temas.update(normalizar(o).split())
    for c in politicos.values():
        for p in c["palabras"]:
            excluir_temas.update(normalizar(p.lstrip("=~")).split())
        excluir_temas.update(normalizar(c["busqueda"]).split())

    comentarios_max = cfg["paginas"] * 100
    resultados = {p: {"POS": 0, "NEG": 0, "NEU": 0} for p in politicos}
    detalle = {}
    ya_analizados = {}
    ids_por_politico = {p: [] for p in politicos}
    limite_cuenta_nueva = datetime.now(timezone.utc) - timedelta(days=DIAS_CUENTA_NUEVA)

    for nombre, config in politicos.items():
        print(f"Buscando videos de {config['busqueda']}...")
        try:
            videos = buscar_videos(config["busqueda"], cfg["region"], cfg["idioma"], cfg["videos"], dias)
        except Exception as e:
            print(f"  Error al buscar videos: {e}")
            continue

        videos_descartados = {"canal_extranjero": 0, "canal_oficial": 0}
        descartes = {"menciona_otros": 0, "mismo_autor": 0, "texto_repetido": 0, "cuenta_nueva": 0, "tope_canal": 0, "ironia": 0}
        otros_politicos = [c["palabras"] for n, c in politicos.items() if n != nombre]

        # 1) Filtrar canales extranjeros u oficiales
        cargar_canales([v[1] for v in videos])
        busqueda_norm = normalizar(config["busqueda"])
        validos = []
        for video_id, canal_id, canal, titulo in videos:
            pais = info_canales.get(canal_id, {}).get("pais")
            if pais and pais != cfg["region"]:
                videos_descartados["canal_extranjero"] += 1
                print(f"    (descartado canal extranjero: {canal}, {pais})")
                continue
            if busqueda_norm in normalizar(canal):
                videos_descartados["canal_oficial"] += 1
                print(f"    (descartado canal oficial: {canal})")
                continue
            validos.append((video_id, canal, titulo))

        # 2) Alcance y videos con mas conversacion
        stats = estadisticas_videos([v[0] for v in validos])
        alcance = {
            "videos": len(validos),
            "vistas": sum(s["vistas"] for s in stats.values()),
            "likes_videos": sum(s["likes"] for s in stats.values()),
        }
        destacados = sorted(validos, key=lambda v: -stats.get(v[0], {}).get("comentarios", 0))[:VIDEOS_DESTACADOS]
        videos_destacados = [{
            "titulo": titulo,
            "canal": canal,
            "url": "https://www.youtube.com/watch?v=" + video_id,
            "comentarios": stats.get(video_id, {}).get("comentarios", 0),
            "vistas": stats.get(video_id, {}).get("vistas", 0),
        } for video_id, canal, titulo in destacados]

        # 3) Tono de los titulos que lo nombran
        titulos = {"POS": 0, "NEG": 0, "NEU": 0}
        for video_id, canal, titulo in validos:
            if menciona(normalizar(titulo), config["palabras"], titulo):
                try:
                    titulos[etiqueta(m["sentimiento"].predict(titulo[:300]).output, TONOS, "NEU")] += 1
                except Exception:
                    pass

        # 4) Comentarios que lo nombran SOLO a el, sin autores ni textos repetidos
        candidatos = {}
        vistos_cid, vistos_autor, vistos_texto = set(), set(), set()
        for video_id, canal, titulo in validos:
            for cid, texto, autor, likes, respuestas in leer_comentarios(video_id, comentarios_max):
                if cid in vistos_cid:
                    continue
                vistos_cid.add(cid)
                norm = normalizar(texto)
                if not menciona(norm, config["palabras"], texto):
                    continue
                if any(menciona(norm, palabras, texto) for palabras in otros_politicos) or menciona(norm, otros_nombres, texto):
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
                candidatos.setdefault(canal, []).append((cid, texto, autor, likes, respuestas))

        # 5) Antiguedad de cuentas, tope por canal y analisis
        cargar_canales([c[2] for lista in candidatos.values() for c in lista])
        canales = {}
        contados = 0
        analizados_politico = []
        ponderado = {"POS": 0, "NEG": 0, "NEU": 0}
        emociones = {v: 0 for v in EMOCIONES.values()}
        agresivos = 0
        respuestas_total = 0
        mas_discutido = {"texto": "", "respuestas": 0}
        temas = Counter()

        for canal, lista in candidatos.items():
            aceptados = []
            for cid, texto, autor, likes, respuestas in lista:
                creado = info_canales.get(autor, {}).get("creado")
                if creado and creado > limite_cuenta_nueva:
                    descartes["cuenta_nueva"] += 1
                    continue
                if len(aceptados) >= MAX_COMENTARIOS_POR_CANAL:
                    descartes["tope_canal"] += 1
                    continue
                aceptados.append((cid, texto, likes, respuestas))

            contados_canal = 0
            for cid, texto, likes, respuestas in aceptados:
                if cid not in ya_analizados:
                    ya_analizados[cid] = analizar(texto, m)
                r = ya_analizados[cid]
                if r.get("i") and EXCLUIR_IRONIA:
                    descartes["ironia"] += 1
                    continue
                s = r["s"]
                resultados[nombre][s] += 1
                ponderado[s] += 1 + likes
                emociones[EMOCIONES.get(r.get("e"), "sin_emocion_clara")] += 1
                if r.get("a"):
                    agresivos += 1
                respuestas_total += respuestas
                if respuestas > mas_discutido["respuestas"]:
                    mas_discutido = {"texto": texto[:220], "respuestas": respuestas}
                temas.update({w for w in normalizar(texto).split()
                              if len(w) >= 4 and w not in stop and w not in excluir_temas and not w.isdigit()})
                analizados_politico.append((s, likes, texto))
                ids_por_politico[nombre].append(cid)
                contados_canal += 1
            if contados_canal:
                canales[canal] = contados_canal
                contados += contados_canal

        def ejemplos_de(tipo):
            lista = sorted([a for a in analizados_politico if a[0] == tipo], key=lambda a: -a[1])
            return [{"texto": t[:280], "likes": l} for _, l, t in lista[:EJEMPLOS_POR_TIPO]]

        canales_ordenados = dict(sorted(canales.items(), key=lambda x: -x[1]))
        pocos_datos = contados < MINIMO_COMENTARIOS or len(canales) < MINIMO_CANALES

        print(f"  {len(validos)} videos validos ({alcance['vistas']} vistas), {contados} comentarios de {len(canales)} canales")
        print(f"  Descartados: {descartes}")
        if pocos_datos:
            print("  AVISO: pocos datos, resultado poco confiable")

        detalle[nombre] = {
            "videos": len(validos),
            "comentarios": contados,
            "pocos_datos": pocos_datos,
            "canales": canales_ordenados,
            "videos_descartados": videos_descartados,
            "comentarios_descartados": descartes,
            "videos_destacados": videos_destacados,
            "ejemplos": {"positivos": ejemplos_de("POS"), "negativos": ejemplos_de("NEG")},
            "emociones": emociones,
            "agresivos": agresivos,
            "ponderado_likes": ponderado,
            "alcance": alcance,
            "polemica": {
                "respuestas": respuestas_total,
                "promedio": round(respuestas_total / contados, 2) if contados else 0,
                "mas_discutido": mas_discutido,
            },
            "titulos": titulos,
            "temas": temas.most_common(TEMAS_POR_DIRIGENTE),
        }

    total = sum(sum(v.values()) for v in resultados.values())
    if total == 0:
        print(f"ERROR: no se pudo analizar ningun comentario de {cfg['nombre']}. No se actualizan sus datos.")
        return False

    hora_ar = datetime.now(timezone(timedelta(hours=-3)))
    hoy = hora_ar.strftime("%Y-%m-%d")
    limite_acum = (hora_ar - timedelta(days=DIAS_ACUMULADO)).strftime("%Y-%m-%d")

    # Acumulado (cada comentario cuenta una sola vez)
    acumulado = leer_json(ruta(codigo, "acumulado.json"), {})
    if acumulado.get("_metodo") != METODO:
        acumulado = {"_metodo": METODO}
    for nombre, ids in ids_por_politico.items():
        registro = acumulado.setdefault(nombre, {})
        for cid in ids:
            if cid not in registro:
                registro[cid] = {"s": ya_analizados[cid]["s"], "f": hoy}
    for nombre in [k for k in acumulado.keys() if k != "_metodo"]:
        acumulado[nombre] = {cid: v for cid, v in acumulado[nombre].items() if v.get("f", "") >= limite_acum}
    datos_acumulados = {}
    for nombre in politicos:
        conteo = {"POS": 0, "NEG": 0, "NEU": 0}
        for v in acumulado.get(nombre, {}).values():
            if v.get("s") in conteo:
                conteo[v["s"]] += 1
        datos_acumulados[nombre] = conteo
    guardar_json(ruta(codigo, "acumulado.json"), acumulado, indent=None)

    # Historial
    historial = leer_json(ruta(codigo, "historial.json"), [])
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
    guardar_json(ruta(codigo, "historial.json"), historial)
    corridas = sum(1 for h in historial if h.get("metodo") == METODO and h.get("fecha_iso", "") >= limite_acum)

    # Datos e info
    guardar_json(ruta(codigo, "datos.json"), resultados)
    info = {
        "pais": cfg["nombre"],
        "codigo": codigo,
        "idioma": cfg["idioma"],
        "actualizado": hora_ar.strftime("%d/%m/%Y %H:%M"),
        "metodo": METODO,
        "fuente": "Comentarios de YouTube",
        "periodo": f"Videos de los ultimos {dias} dias",
        "filtros": {
            "solo_un_dirigente_por_comentario": True,
            "otros_nombres_excluidos": otros_nombres,
            "ironia_excluida": EXCLUIR_IRONIA and m.get("ironia") is not None,
            "tope_por_canal": MAX_COMENTARIOS_POR_CANAL,
            "un_comentario_por_persona": True,
            "sin_textos_repetidos": True,
            "cuentas_nuevas_excluidas_dias": DIAS_CUENTA_NUEVA,
            "sin_canales_extranjeros_ni_oficiales": True,
        },
        "modelos": {
            "emociones": m.get("emocion") is not None,
            "agresividad": m.get("odio") is not None,
            "ironia": m.get("ironia") is not None,
        },
        "minimo_confiable": {"comentarios": MINIMO_COMENTARIOS, "canales": MINIMO_CANALES},
        "total_comentarios": total,
        "acumulado": {
            "dias": DIAS_ACUMULADO,
            "corridas": corridas,
            "datos": datos_acumulados,
            "pocos_datos": {n: sum(d.values()) < MINIMO_COMENTARIOS for n, d in datos_acumulados.items()},
        },
        "detalle": detalle,
    }
    guardar_json(ruta(codigo, "info.json"), info)

    if codigo == "ar":
        for archivo in ("datos.json", "info.json", "historial.json", "acumulado.json"):
            shutil.copy(ruta("ar", archivo), archivo)

    # Indice de paises para la web
    indice = leer_json(os.path.join(CARPETA, "paises.json"), {})
    for c, conf in PAISES.items():
        indice.setdefault(c, {"nombre": conf["nombre"], "idioma": conf["idioma"]})
        indice[c]["nombre"] = conf["nombre"]
    indice[codigo].update({"actualizado": info["actualizado"], "total_comentarios": total})
    guardar_json(os.path.join(CARPETA, "paises.json"), indice)

    # Aviso por Telegram si hay cambios fuertes
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
    if cambios and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        enviar_telegram(f"📊 Monitor Político ({cfg['nombre']}): cambios fuertes\n\n" + "\n".join(cambios) + f"\n\n{URL_WEB}")

    print(f"Listo {cfg['nombre']}: {total} comentarios. Acumulado de {corridas} corrida(s).")
    return True


# ============================================================
# EJECUCION
# ============================================================
elegido = normalizar(PAIS_ELEGIDO)
if elegido in ("todos", ""):
    codigos = sorted(PAISES.keys(), key=lambda c: (PAISES[c]["idioma"] != "es", PAISES[c]["idioma"], c != "ar", c))
else:
    codigos = [c for c, conf in PAISES.items() if elegido in (c, normalizar(conf["nombre"]))]
    if not codigos:
        print(f"ERROR: no conozco el pais '{PAIS_ELEGIDO}'.")
        sys.exit(1)

os.makedirs(CARPETA, exist_ok=True)
estado = {}
for codigo in codigos:
    try:
        estado[codigo] = procesar_pais(codigo, PAISES[codigo])
    except Exception as e:
        print(f"ERROR procesando {PAISES[codigo]['nombre']}: {e}")
        estado[codigo] = False

print("")
print("RESUMEN:")
for codigo, ok in estado.items():
    print(f"  {PAISES[codigo]['nombre']}: {'OK' if ok else 'SIN ACTUALIZAR'}")

if not any(estado.values()):
    sys.exit(1)
