from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import anthropic
import os
import random
import string
from datetime import datetime, timedelta
import databases
import sqlalchemy

DATABASE_URL = os.getenv("DATABASE_URL", "")

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

usuarios = sqlalchemy.Table(
    "usuarios", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("celular", sqlalchemy.String(20), unique=True),
    sqlalchemy.Column("nombre", sqlalchemy.String(100)),
    sqlalchemy.Column("codigo_verificacion", sqlalchemy.String(6)),
    sqlalchemy.Column("verificado", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("estado", sqlalchemy.String(20), default="trial"),
    sqlalchemy.Column("fecha_vencimiento", sqlalchemy.DateTime),
    sqlalchemy.Column("codigo_referido", sqlalchemy.String(10), unique=True),
    sqlalchemy.Column("referido_por", sqlalchemy.String(10)),
    sqlalchemy.Column("descuento_proximo_mes", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.now),
)

pagos = sqlalchemy.Table(
    "pagos", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("usuario_id", sqlalchemy.Integer),
    sqlalchemy.Column("monto_gs", sqlalchemy.Integer),
    sqlalchemy.Column("mes", sqlalchemy.String(7)),
    sqlalchemy.Column("comprobante", sqlalchemy.Text),
    sqlalchemy.Column("estado", sqlalchemy.String(20), default="pendiente"),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.now),
)

viajes_log = sqlalchemy.Table(
    "viajes_log", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("usuario_id", sqlalchemy.Integer),
    sqlalchemy.Column("origen", sqlalchemy.Text),
    sqlalchemy.Column("destino", sqlalchemy.Text),
    sqlalchemy.Column("distancia_km", sqlalchemy.Float),
    sqlalchemy.Column("tarifa_gs", sqlalchemy.Integer),
    sqlalchemy.Column("ganancia_gs", sqlalchemy.Integer),
    sqlalchemy.Column("decision", sqlalchemy.String(10)),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.now),
)

app = FastAPI(title="VozViaje Backend", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    await database.connect()
    engine = sqlalchemy.create_engine(DATABASE_URL)
    metadata.create_all(engine)
    print("DB inicializada OK")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

def gen_codigo():
    return ''.join(random.choices(string.digits, k=6))

def gen_referido():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

COSTO_NAFTA_KM = 1200
PRECIO_MENSUAL = 30000

class RegistroRequest(BaseModel):
    celular: str
    nombre: str
    codigo_referido: Optional[str] = None

class VerificacionRequest(BaseModel):
    celular: str
    codigo: str

class EstadoRequest(BaseModel):
    celular: str

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
    celular: Optional[str] = None

class PagoRequest(BaseModel):
    celular: str
    comprobante: Optional[str] = None

@app.post("/registro")
async def registro(data: RegistroRequest):
    existente = await database.fetch_one(usuarios.select().where(usuarios.c.celular == data.celular))
    codigo = gen_codigo()
    if existente:
        await database.execute(usuarios.update().where(usuarios.c.celular == data.celular).values(codigo_verificacion=codigo))
        return {"mensaje": "Código enviado", "codigo_debug": codigo, "es_nuevo": False}
    codigo_ref = gen_referido()
    fecha_venc = datetime.now() + timedelta(days=30)
    await database.execute(usuarios.insert().values(
        celular=data.celular, nombre=data.nombre, codigo_verificacion=codigo,
        codigo_referido=codigo_ref, referido_por=data.codigo_referido, fecha_vencimiento=fecha_venc
    ))
    return {"mensaje": "Registro exitoso. Código enviado.", "codigo_debug": codigo, "es_nuevo": True}

@app.post("/verificar")
async def verificar(data: VerificacionRequest):
    u = await database.fetch_one(usuarios.select().where(usuarios.c.celular == data.celular))
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if u["codigo_verificacion"] != data.codigo:
        raise HTTPException(status_code=400, detail="Código incorrecto")
    await database.execute(usuarios.update().where(usuarios.c.celular == data.celular).values(verificado=True))
    dias = max(0, (u["fecha_vencimiento"] - datetime.now()).days) if u["fecha_vencimiento"] else 30
    return {
        "mensaje": "Verificación exitosa",
        "usuario": {
            "celular": u["celular"], "nombre": u["nombre"], "estado": u["estado"],
            "codigo_referido": u["codigo_referido"], "dias_restantes": dias,
            "descuento_proximo_mes": u["descuento_proximo_mes"],
        }
    }

@app.post("/estado-cuenta")
async def estado_cuenta(data: EstadoRequest):
    u = await database.fetch_one(usuarios.select().where(usuarios.c.celular == data.celular))
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    dias = max(0, (u["fecha_vencimiento"] - datetime.now()).days) if u["fecha_vencimiento"] else 0
    estado = u["estado"]
    if dias <= 0 and estado == "trial":
        await database.execute(usuarios.update().where(usuarios.c.celular == data.celular).values(estado="vencido"))
        estado = "vencido"
    stats = await database.fetch_one(
        sqlalchemy.text("SELECT COUNT(*) as total, SUM(CASE WHEN decision = 'aceptado' THEN 1 ELSE 0 END) as aceptados FROM viajes_log WHERE usuario_id = :uid"),
        {"uid": u["id"]}
    )
    precio = int(PRECIO_MENSUAL * 0.5) if u["descuento_proximo_mes"] else PRECIO_MENSUAL
    return {
        "celular": u["celular"], "nombre": u["nombre"], "estado": estado, "dias_restantes": dias,
        "codigo_referido": u["codigo_referido"],
        "link_referido": f"https://vozviaje.app/unirse?ref={u['codigo_referido']}",
        "descuento_proximo_mes": u["descuento_proximo_mes"], "precio_mes_gs": precio,
        "stats": {"total_viajes": stats["total"] or 0, "aceptados": stats["aceptados"] or 0}
    }

@app.post("/confirmar-pago")
async def confirmar_pago(data: PagoRequest):
    u = await database.fetch_one(usuarios.select().where(usuarios.c.celular == data.celular))
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    tiene_descuento = u["descuento_proximo_mes"]
    monto = int(PRECIO_MENSUAL * 0.5) if tiene_descuento else PRECIO_MENSUAL
    mes = datetime.now().strftime("%Y-%m")
    await database.execute(pagos.insert().values(usuario_id=u["id"], monto_gs=monto, mes=mes, comprobante=data.comprobante))
    nueva_fecha = datetime.now() + timedelta(days=30)
    await database.execute(usuarios.update().where(usuarios.c.celular == data.celular).values(
        estado="activo", fecha_vencimiento=nueva_fecha, descuento_proximo_mes=False
    ))
    if u["referido_por"]:
        ref = await database.fetch_one(usuarios.select().where(usuarios.c.codigo_referido == u["referido_por"]))
        if ref:
            await database.execute(usuarios.update().where(usuarios.c.id == ref["id"]).values(descuento_proximo_mes=True))
    return {"mensaje": "Pago registrado. Cuenta activa 30 días más.", "monto_gs": monto, "descuento_aplicado": tiene_descuento}

def analisis_local(datos: DatosViaje) -> dict:
    costo = int(datos.distancia_km * COSTO_NAFTA_KM)
    comision = int(datos.tarifa_estimada_gs * 0.25)
    ganancia = datos.tarifa_estimada_gs - costo - comision
    alertas = []
    if datos.pasajero_calificacion < 4.0:
        alertas.append(f"Calificación baja del pasajero: {datos.pasajero_calificacion}")
    if datos.distancia_km > 30:
        alertas.append("Viaje largo, verificá combustible")
    if ganancia < 12000:
        alertas.append("Ganancia neta baja")
    if ganancia >= 30000 and datos.pasajero_calificacion >= 4.5:
        v, c = "Conveniente", True
    elif ganancia >= 12000:
        v, c = "Regular", True
    else:
        v, c = "No conviene", False
    return {"ganancia_neta_gs": ganancia, "veredicto": v, "conviene": c, "alertas": alertas}

@app.post("/analizar-viaje")
async def analizar_viaje(datos: DatosViaje):
    usuario_id = None
    if datos.celular:
        try:
            u = await database.fetch_one(usuarios.select().where(usuarios.c.celular == datos.celular))
            if u:
                dias = (u["fecha_vencimiento"] - datetime.now()).days if u["fecha_vencimiento"] else 0
                if dias <= 0 and u["estado"] not in ["activo"]:
                    raise HTTPException(status_code=403, detail="Suscripción vencida. Renová para continuar.")
                usuario_id = u["id"]
        except HTTPException:
            raise
        except:
            pass

    calc = analisis_local(datos)
    gs = f"{calc['ganancia_neta_gs']:,}".replace(",", ".")
    resumen_voz = (
        f"Nuevo viaje. {datos.pasajero_nombre}, calificación {datos.pasajero_calificacion}. "
        f"De {datos.origen} a {datos.destino}. {datos.distancia_km} kilómetros, {datos.duracion_min} minutos. "
        f"Tarifa {datos.tarifa_estimada_gs:,} guaraníes. Ganancia estimada {gs} guaraníes. Veredicto: {calc['veredicto']}."
    )
    analisis = (
        f"Viaje de {datos.distancia_km}km en {datos.duracion_min} min. "
        f"Tarifa: Gs. {datos.tarifa_estimada_gs:,}. Comisión: Gs. {int(datos.tarifa_estimada_gs*0.25):,}. "
        f"Combustible: Gs. {int(datos.distancia_km*COSTO_NAFTA_KM):,}. Ganancia neta: Gs. {calc['ganancia_neta_gs']:,}."
    )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key and api_key != "TU_API_KEY_AQUI":
        try:
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": f"""Sos un asistente para conductores de Uber/Bolt en Paraguay.
Analizá este viaje en español paraguayo. Sin asteriscos ni markdown. Solo texto plano.
- Pasajero: {datos.pasajero_nombre} (calificación {datos.pasajero_calificacion}/5, {datos.pasajero_total_viajes} viajes)
- De {datos.origen} a {datos.destino}, {datos.distancia_km}km, {datos.duracion_min} min
- Tarifa: Gs. {datos.tarifa_estimada_gs:,} | Ganancia neta: Gs. {calc['ganancia_neta_gs']:,}
- Hora: {datos.hora_actual or 'no especificada'}
Máximo 3 oraciones. Di si conviene o no y por qué."""}]
            )
            analisis = msg.content[0].text
        except Exception as e:
            analisis += f" (IA no disponible: {str(e)})"

    if usuario_id:
        try:
            await database.execute(viajes_log.insert().values(
                usuario_id=usuario_id, origen=datos.origen, destino=datos.destino,
                distancia_km=datos.distancia_km, tarifa_gs=datos.tarifa_estimada_gs,
                ganancia_gs=calc["ganancia_neta_gs"]
            ))
        except:
            pass

    return {
        "conviene": calc["conviene"], "veredicto": calc["veredicto"],
        "ganancia_neta_gs": calc["ganancia_neta_gs"], "resumen_voz": resumen_voz,
        "analisis_detallado": analisis, "alertas": calc["alertas"],
    }

@app.post("/registrar-decision")
async def registrar_decision(data: dict):
    celular = data.get("celular")
    decision = data.get("decision")
    if not celular or not decision:
        return {"ok": True}
    try:
        u = await database.fetch_one(usuarios.select().where(usuarios.c.celular == celular))
        if u:
            await database.execute(
                sqlalchemy.text("UPDATE viajes_log SET decision = :d WHERE usuario_id = :uid AND decision IS NULL ORDER BY created_at DESC LIMIT 1"),
                {"d": decision, "uid": u["id"]}
            )
    except:
        pass
    return {"ok": True}

@app.get("/")
def root():
    return {"status": "VozViaje backend corriendo", "version": "2.0.0"}

@app.get("/health")
async def health():
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    db_ok = database.is_connected
    return {
        "status": "ok",
        "ia_configurada": bool(api_key and api_key != "TU_API_KEY_AQUI"),
        "db_conectada": db_ok,
        "timestamp": datetime.now().isoformat()
    }