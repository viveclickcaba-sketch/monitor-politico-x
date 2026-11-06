import json
import os
import tweepy
from pysentimiento import create_analyzer

# Leer la clave guardada en GitHub Secrets
BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

if not BEARER_TOKEN:
    raise ValueError("No se encontró el X_BEARER_TOKEN en las variables de entorno.")

client = tweepy.Client(bearer_token=BEARER_TOKEN)
analyzer = create_analyzer(task="sentiment", lang="es")

# Búsqueda de publicaciones en español sobre política o debate público
QUERY = "elecciones OR candidatos OR 'buenos aires' -is:retweet lang:es"

try:
    response = client.search_recent_tweets(query=QUERY, max_results=50, tweet_fields=["created_at", "text"])
    
    resultados = []
    if response.data:
        for tweet in response.data:
            analisis = analyzer.predict(tweet.text)
            resultados.append({
                "texto": tweet.text,
                "fecha": str(tweet.created_at),
                "sentimiento": analisis.output,
                "probabilidad": float(analisis.probas[analisis.output])
            })
    
    with open("datos.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=4)
        
    print(f"¡Éxito! Se procesaron {len(resultados)} publicaciones.")

except Exception as e:
    print(f"Error al conectar con X: {e}")
