import json
import os
import tweepy
from pysentimiento import create_analyzer

BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
analyzer = create_analyzer(task="sentiment", lang="es")

# Lista de políticos a monitorear
POLITICOS = ["Milei", "Massa", "Kicillof", "Macri", "Bullrich"]

# Si no hay token de X, generamos datos simulados completos con nombres para probar
if not BEARER_TOKEN:
    print("Modo prueba: generando datos por político...")
    resultados_por_politico = {
        "Milei": {"POS": 12, "NEG": 8, "NEU": 5},
        "Massa": {"POS": 5, "NEG": 15, "NEU": 4},
        "Kicillof": {"POS": 8, "NEG": 10, "NEU": 6},
        "Macri": {"POS": 9, "NEG": 7, "NEU": 8},
        "Bullrich": {"POS": 10, "NEG": 6, "NEU": 3}
    }
else:
    client = tweepy.Client(bearer_token=BEARER_TOKEN)
    QUERY = "(" + " OR ".join(POLITICOS) + ") -is:retweet lang:es"
    
    resultados_por_politico = {p: {"POS": 0, "NEG": 0, "NEU": 0} for p in POLITICOS}
    
    try:
        response = client.search_recent_tweets(query=QUERY, max_results=100)
        if response.data:
            for tweet in response.data:
                texto = tweet.text
                analisis = analyzer.predict(texto)
                sentimiento = analisis.output # POS, NEG, NEU
                
                # Asignar el sentimiento al político mencionado en el texto
                for politico in POLITICOS:
                    if politico.lower() in texto.lower():
                        resultados_por_politico[politico][sentimiento] += 1
    except Exception as e:
        print(f"Error al conectar con X: {e}")

with open("datos.json", "w", encoding="utf-8") as f:
    json.dump(resultados_por_politico, f, ensure_ascii=False, indent=4)

print("¡Datos agrupados por político guardados en datos.json!")
