from fastapi import FastAPI, HTTPException, Query
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

app = FastAPI(title="VozViaje Backend", version="2.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ADMIN_KEY = os.getenv("ADMIN_KEY", "vozviaje2024")  # Cambiá esto en Railway vars

@app.on_event("startup")
async def startup():
    await database.connect()
    import asyncpg
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            celular VARCHAR(20) UNIQUE NOT NULL,
            nombre VARCHAR(100),
            codigo_verificacion VARCHAR(6),
            verificado BOOLEAN DEFAULT FALSE,
            estado VARCHAR(20) DEFAULT 'trial',
            fecha_vencimiento TIMESTAMP,
            codigo_referido VARCHAR(10) UNIQUE,
            referido_por VARCHAR(10),
            descuento_proximo_mes BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS pagos (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER,
            monto_gs INTEGER,
            mes VARCHAR(7),
            comprobante TEXT,
            estado VARCHAR(20) DEFAULT 'pendiente',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS viajes_log (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER,
            origen TEXT,
            destino TEXT,
            distancia_km FLOAT,
            tarifa_gs INTEGER,
            ganancia_gs INTEGER,
            decision VARCHAR(10),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    await conn.close()
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
        estado='trial', descuento_proximo_mes=False,
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
        sqlalchemy.text(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN decision = 'aceptado' THEN 1 ELSE 0 END) as aceptados "
            "FROM viajes_log WHERE usuario_id = :uid"
        ).bindparams(uid=u["id"])
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

# ─── PANEL ADMIN ──────────────────────────────────────────────────────────────

@app.get("/admin/usuarios")
async def admin_usuarios(key: str = Query(...)):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="No autorizado")
    rows = await database.fetch_all(
        usuarios.select().order_by(usuarios.c.created_at.desc())
    )
    result = []
    for u in rows:
        dias = max(0, (u["fecha_vencimiento"] - datetime.now()).days) if u["fecha_vencimiento"] else 0
        result.append({
            "id": u["id"],
            "celular": u["celular"],
            "nombre": u["nombre"],
            "estado": u["estado"],
            "verificado": u["verificado"],
            "dias_restantes": dias,
            "codigo_referido": u["codigo_referido"],
            "referido_por": u["referido_por"],
            "descuento_proximo_mes": u["descuento_proximo_mes"],
            "created_at": u["created_at"].isoformat() if u["created_at"] else None,
        })
    return {"total": len(result), "usuarios": result}

@app.get("/admin/pagos")
async def admin_pagos(key: str = Query(...)):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="No autorizado")
    rows = await database.fetch_all(
        sqlalchemy.text("""
            SELECT p.*, u.celular, u.nombre
            FROM pagos p
            JOIN usuarios u ON u.id = p.usuario_id
            ORDER BY p.created_at DESC
        """)
    )
    return {"total": len(rows), "pagos": [dict(r) for r in rows]}

@app.get("/admin/stats")
async def admin_stats(key: str = Query(...)):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="No autorizado")
    total = await database.fetch_one(sqlalchemy.text("SELECT COUNT(*) as n FROM usuarios"))
    activos = await database.fetch_one(sqlalchemy.text("SELECT COUNT(*) as n FROM usuarios WHERE estado = 'activo'"))
    trial = await database.fetch_one(sqlalchemy.text("SELECT COUNT(*) as n FROM usuarios WHERE estado = 'trial'"))
    vencidos = await database.fetch_one(sqlalchemy.text("SELECT COUNT(*) as n FROM usuarios WHERE estado = 'vencido'"))
    ingresos = await database.fetch_one(sqlalchemy.text("SELECT COALESCE(SUM(monto_gs), 0) as total FROM pagos"))
    viajes = await database.fetch_one(sqlalchemy.text("SELECT COUNT(*) as n FROM viajes_log"))
    return {
        "usuarios": {
            "total": total["n"],
            "activos": activos["n"],
            "trial": trial["n"],
            "vencidos": vencidos["n"],
        },
        "ingresos_totales_gs": ingresos["total"],
        "viajes_analizados": viajes["n"],
    }

@app.post("/admin/activar")
async def admin_activar(data: dict, key: str = Query(...)):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="No autorizado")
    celular = data.get("celular")
    if not celular:
        raise HTTPException(status_code=400, detail="Falta celular")
    u = await database.fetch_one(usuarios.select().where(usuarios.c.celular == celular))
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    nueva_fecha = datetime.now() + timedelta(days=30)
    await database.execute(
        usuarios.update().where(usuarios.c.celular == celular).values(estado="activo", fecha_vencimiento=nueva_fecha)
    )
    return {"mensaje": f"Cuenta {celular} activada por 30 días"}

# ─── ENDPOINTS EXISTENTES ─────────────────────────────────────────────────────

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
    return {"status": "VozViaje backend corriendo", "version": "2.1.0"}

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