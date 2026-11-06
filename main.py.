# Instalación previa requerida en tu PC: pip install pysentimiento
from pysentimiento import create_analyzer
import json

analyzer = create_analyzer(task="sentiment", lang="es")

# Ejemplos de prueba (simulando mensajes leídos de X)
tweets = [
    "Excelente la nueva propuesta de transporte público para la ciudad.",
    "Una vergüenza la gestión de las obras en la avenida principal.",
    "Mañana se presentará el informe económico a las 10 hs."
]

resultados = []
for tweet in tweets:
    analisis = analyzer.predict(tweet)
    resultados.append({
        "texto": tweet,
        "sentimiento": analisis.output,  # POS (Positivo), NEG (Negativo), NEU (Neutral)
        "probabilidades": analisis.probas
    })

# Guardamos los resultados procesados en un archivo JSON
with open("datos.json", "w", encoding="utf-8") as f:
    json.dump(resultados, f, ensure_ascii=False, indent=4)

print("¡Análisis completado y datos guardados en datos.json!")
