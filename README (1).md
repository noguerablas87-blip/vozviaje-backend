# VozViaje — Backend

Backend en FastAPI para el análisis de viajes de Uber/Bolt.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Estado del servidor |
| GET | `/health` | Verifica si la IA está configurada |
| POST | `/analizar-viaje` | Analiza un viaje (lógica local + IA opcional) |
| POST | `/generar-reporte` | Genera reporte mensual del conductor (requiere IA) |

## Deploy en Railway

1. Creá una cuenta en https://railway.app
2. Nuevo proyecto → "Deploy from GitHub repo"
3. Subí esta carpeta a un repo de GitHub
4. En Railway, andá a Variables y agregá:
   ```
   ANTHROPIC_API_KEY=tu_key_aqui
   ```
5. Railway detecta el `nixpacks.toml` y hace el deploy automático.
6. Copiá la URL pública que te da Railway (ej: `https://vozviaje-backend.up.railway.app`)

## Correr localmente

```bash
pip install -r requirements.txt
cp .env.example .env
# Editá .env con tu API key
uvicorn main:app --reload --port 8000
```

Documentación interactiva en: http://localhost:8000/docs

## Ejemplo de llamada a /analizar-viaje

```json
POST /analizar-viaje
{
  "pasajero_nombre": "Carlos M.",
  "pasajero_calificacion": 4.8,
  "pasajero_total_viajes": 342,
  "origen": "Shopping del Sol",
  "destino": "Aeropuerto Silvio Pettirossi",
  "distancia_km": 18.4,
  "duracion_min": 22,
  "tarifa_estimada_gs": 78000,
  "hora_actual": "18:30"
}
```

## Respuesta esperada

```json
{
  "conviene": true,
  "veredicto": "Conveniente",
  "ganancia_neta_gs": 55700,
  "resumen_voz": "Nuevo viaje. Carlos M., calificación 4.8...",
  "analisis_detallado": "Viaje conveniente. Ruta directa sin complicaciones...",
  "alertas": []
}
```
