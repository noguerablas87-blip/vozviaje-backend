from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import anthropic
import os
from datetime import datetime

app = FastAPI(title="VozViaje Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Modelos de datos ---

class DatosViaje(BaseModel):
    pasajero_nombre: str
    pasajero_calificacion: float
    pasajero_total_viajes: int
    origen: str
    destino: str
    distancia_km: float
    duracion_min: int
    tarifa_estimada_gs: int
    hora_actual: Optional[str] = None

class RespuestaAnalisis(BaseModel):
    conviene: bool
    veredicto: str           # "Conveniente" / "Regular" / "No conviene"
    ganancia_neta_gs: int
    resumen_voz: str         # Texto corto para leer en voz alta
    analisis_detallado: str  # Análisis completo de la IA
    alertas: list[str]       # Lista de alertas si hay

class DatosReporte(BaseModel):
    conductor_nombre: str
    mes: str
    viajes: list[dict]       # Lista de viajes del mes con sus datos

# --- Lógica local de cálculo ---

COSTO_NAFTA_KM = 1200  # Gs. aprox por km (ajustable)

def calcular_ganancia_local(datos: DatosViaje) -> int:
    costo_combustible = int(datos.distancia_km * COSTO_NAFTA_KM)
    comision_plataforma = int(datos.tarifa_estimada_gs * 0.25)
    ganancia = datos.tarifa_estimada_gs - costo_combustible - comision_plataforma
    return ganancia

def analisis_local_rapido(datos: DatosViaje) -> dict:
    ganancia = calcular_ganancia_local(datos)
    alertas = []

    if datos.pasajero_calificacion < 4.0:
        alertas.append(f"Calificación baja del pasajero: {datos.pasajero_calificacion}")
    if datos.distancia_km > 30:
        alertas.append("Viaje largo, verificá combustible")
    if ganancia < 15000:
        alertas.append("Ganancia neta baja")

    if ganancia >= 40000 and datos.pasajero_calificacion >= 4.5:
        veredicto = "Conveniente"
        conviene = True
    elif ganancia >= 20000:
        veredicto = "Regular"
        conviene = True
    else:
        veredicto = "No conviene"
        conviene = False

    return {
        "ganancia_neta_gs": ganancia,
        "veredicto": veredicto,
        "conviene": conviene,
        "alertas": alertas,
    }

def construir_resumen_voz(datos: DatosViaje, calc: dict) -> str:
    gs_format = f"{calc['ganancia_neta_gs']:,}".replace(",", ".")
    return (
        f"Nuevo viaje. {datos.pasajero_nombre}, "
        f"calificación {datos.pasajero_calificacion}. "
        f"De {datos.origen} a {datos.destino}. "
        f"{datos.distancia_km} kilómetros, {datos.duracion_min} minutos. "
        f"Tarifa {datos.tarifa_estimada_gs:,} guaraníes. "
        f"Ganancia estimada {gs_format} guaraníes. "
        f"Veredicto: {calc['veredicto']}."
    )

# --- Endpoints ---

@app.get("/")
def root():
    return {"status": "VozViaje backend corriendo", "version": "1.0.0"}

@app.post("/analizar-viaje", response_model=RespuestaAnalisis)
def analizar_viaje(datos: DatosViaje):
    """
    Analiza un viaje usando lógica local.
    Si hay API key de Anthropic configurada, enriquece el análisis con IA.
    """
    calc = analisis_local_rapido(datos)
    resumen_voz = construir_resumen_voz(datos, calc)
    analisis_detallado = (
        f"Viaje de {datos.distancia_km}km estimado en {datos.duracion_min} min. "
        f"Tarifa bruta: Gs. {datos.tarifa_estimada_gs:,}. "
        f"Comisión plataforma (25%): Gs. {int(datos.tarifa_estimada_gs * 0.25):,}. "
        f"Combustible estimado: Gs. {int(datos.distancia_km * COSTO_NAFTA_KM):,}. "
        f"Ganancia neta: Gs. {calc['ganancia_neta_gs']:,}."
    )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key and api_key != "TU_API_KEY_AQUI":
        try:
            client = anthropic.Anthropic(api_key=api_key)
            prompt = f"""Sos un asistente para conductores de Uber/Bolt en Paraguay.
Analizá este viaje y dá un análisis breve en español paraguayo. 
NO uses asteriscos, negritas ni ningún formato markdown. Solo texto plano.

Datos del viaje:
- Pasajero: {datos.pasajero_nombre} (calificación {datos.pasajero_calificacion}/5, {datos.pasajero_total_viajes} viajes)
- Origen: {datos.origen}
- Destino: {datos.destino}
- Distancia: {datos.distancia_km} km
- Duración estimada: {datos.duracion_min} minutos
- Tarifa estimada: Gs. {datos.tarifa_estimada_gs:,}
- Ganancia neta estimada: Gs. {calc['ganancia_neta_gs']:,}
- Hora: {datos.hora_actual or 'no especificada'}

Respondé en máximo 3 oraciones. Di claramente si conviene o no conviene, y por qué. Sin markdown."""

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            analisis_detallado = message.content[0].text
        except Exception as e:
            analisis_detallado += f" (IA no disponible: {str(e)})"

    return RespuestaAnalisis(
        conviene=calc["conviene"],
        veredicto=calc["veredicto"],
        ganancia_neta_gs=calc["ganancia_neta_gs"],
        resumen_voz=resumen_voz,
        analisis_detallado=analisis_detallado,
        alertas=calc["alertas"],
    )

@app.post("/generar-reporte")
def generar_reporte(datos: DatosReporte):
    """
    Genera el reporte mensual del conductor.
    Este endpoint SÍ usa Claude (se llama una vez al mes por conductor).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "TU_API_KEY_AQUI":
        raise HTTPException(status_code=503, detail="API key de Anthropic no configurada")

    total_viajes = len(datos.viajes)
    aceptados = [v for v in datos.viajes if v.get("aceptado")]
    rechazados = [v for v in datos.viajes if not v.get("aceptado")]
    ganancia_total = sum(v.get("ganancia_gs", 0) for v in aceptados)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""Sos un asistente financiero para conductores de Uber/Bolt en Paraguay.
Generá un reporte mensual amigable y motivador para {datos.conductor_nombre}.

Resumen del mes de {datos.mes}:
- Total de viajes recibidos: {total_viajes}
- Viajes aceptados: {len(aceptados)}
- Viajes rechazados (por bajo margen): {len(rechazados)}
- Ganancia neta total estimada: Gs. {ganancia_total:,}

Escribí un análisis en 3-4 oraciones. Destacá logros, mencioná oportunidades de mejora y motivá al conductor. Usá un tono cercano y directo."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )

        return {
            "conductor": datos.conductor_nombre,
            "mes": datos.mes,
            "stats": {
                "total_viajes": total_viajes,
                "aceptados": len(aceptados),
                "rechazados": len(rechazados),
                "ganancia_total_gs": ganancia_total,
                "tasa_aceptacion": round(len(aceptados) / total_viajes * 100) if total_viajes > 0 else 0,
            },
            "analisis_ia": message.content[0].text,
            "generado_el": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    return {
        "status": "ok",
        "ia_configurada": bool(api_key and api_key != "TU_API_KEY_AQUI"),
        "timestamp": datetime.now().isoformat(),
    }
