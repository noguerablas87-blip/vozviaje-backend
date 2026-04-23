from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import anthropic
import os
import random
import string
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="VozViaje Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)

def init_db():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            celular VARCHAR(20) UNIQUE NOT NULL,
            nombre VARCHAR(100),
            codigo_verificacion VARCHAR(6),
            verificado BOOLEAN DEFAULT FALSE,
            estado VARCHAR(20) DEFAULT 'trial',
            fecha_registro TIMESTAMP DEFAULT NOW(),
            fecha_vencimiento TIMESTAMP,
            codigo_referido VARCHAR(10) UNIQUE,
            referido_por VARCHAR(10),
            descuento_proximo_mes BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS pagos (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            monto_gs INTEGER NOT NULL,
            mes VARCHAR(7) NOT NULL,
            comprobante TEXT,
            estado VARCHAR(20) DEFAULT 'pendiente',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS viajes_log (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            origen TEXT,
            destino TEXT,
            distancia_km FLOAT,
            tarifa_gs INTEGER,
            ganancia_gs INTEGER,
            decision VARCHAR(10),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.on_event("startup")
def startup():
    try:
        init_db()
        print("Base de datos inicializada OK")
    except Exception as e:
        print(f"Error inicializando DB: {e}")

def generar_codigo():
    return ''.join(random.choices(string.digits, k=6))

def generar_codigo_referido():
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
def registro(data: RegistroRequest):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM usuarios WHERE celular = %s", (data.celular,))
        existente = cur.fetchone()
        codigo = generar_codigo()
        if existente:
            cur.execute("UPDATE usuarios SET codigo_verificacion = %s WHERE celular = %s", (codigo, data.celular))
            conn.commit()
            return {"mensaje": "Código enviado", "codigo_debug": codigo, "es_nuevo": False}
        codigo_ref = generar_codigo_referido()
        fecha_venc = datetime.now() + timedelta(days=30)
        cur.execute("""
            INSERT INTO usuarios (celular, nombre, codigo_verificacion, codigo_referido, referido_por, fecha_vencimiento)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (data.celular, data.nombre, codigo, codigo_ref, data.codigo_referido, fecha_venc))
        conn.commit()
        return {"mensaje": "Registro exitoso. Código enviado.", "codigo_debug": codigo, "es_nuevo": True}
    finally:
        cur.close()
        conn.close()

@app.post("/verificar")
def verificar(data: VerificacionRequest):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM usuarios WHERE celular = %s", (data.celular,))
        usuario = cur.fetchone()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        if usuario["codigo_verificacion"] != data.codigo:
            raise HTTPException(status_code=400, detail="Código incorrecto")
        cur.execute("UPDATE usuarios SET verificado = TRUE WHERE celular = %s", (data.celular,))
        conn.commit()
        dias = max(0, (usuario["fecha_vencimiento"] - datetime.now()).days) if usuario["fecha_vencimiento"] else 30
        return {
            "mensaje": "Verificación exitosa",
            "usuario": {
                "celular": usuario["celular"],
                "nombre": usuario["nombre"],
                "estado": usuario["estado"],
                "codigo_referido": usuario["codigo_referido"],
                "dias_restantes": dias,
                "descuento_proximo_mes": usuario["descuento_proximo_mes"],
            }
        }
    finally:
        cur.close()
        conn.close()

@app.post("/estado-cuenta")
def estado_cuenta(data: EstadoRequest):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM usuarios WHERE celular = %s", (data.celular,))
        usuario = cur.fetchone()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        dias = max(0, (usuario["fecha_vencimiento"] - datetime.now()).days) if usuario["fecha_vencimiento"] else 0
        estado = usuario["estado"]
        if dias <= 0 and estado == "trial":
            cur.execute("UPDATE usuarios SET estado = 'vencido' WHERE celular = %s", (data.celular,))
            conn.commit()
            estado = "vencido"
        cur.execute("""
            SELECT COUNT(*) as total, SUM(CASE WHEN decision = 'aceptado' THEN 1 ELSE 0 END) as aceptados
            FROM viajes_log WHERE usuario_id = %s
        """, (usuario["id"],))
        stats = cur.fetchone()
        precio = int(PRECIO_MENSUAL * 0.5) if usuario["descuento_proximo_mes"] else PRECIO_MENSUAL
        return {
            "celular": usuario["celular"],
            "nombre": usuario["nombre"],
            "estado": estado,
            "dias_restantes": dias,
            "codigo_referido": usuario["codigo_referido"],
            "link_referido": f"https://vozviaje.app/unirse?ref={usuario['codigo_referido']}",
            "descuento_proximo_mes": usuario["descuento_proximo_mes"],
            "precio_mes_gs": precio,
            "stats": {"total_viajes": stats["total"] or 0, "aceptados": stats["aceptados"] or 0}
        }
    finally:
        cur.close()
        conn.close()

@app.post("/confirmar-pago")
def confirmar_pago(data: PagoRequest):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM usuarios WHERE celular = %s", (data.celular,))
        usuario = cur.fetchone()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        tiene_descuento = usuario["descuento_proximo_mes"]
        monto = int(PRECIO_MENSUAL * 0.5) if tiene_descuento else PRECIO_MENSUAL
        mes = datetime.now().strftime("%Y-%m")
        cur.execute("INSERT INTO pagos (usuario_id, monto_gs, mes, comprobante) VALUES (%s, %s, %s, %s)",
                    (usuario["id"], monto, mes, data.comprobante))
        nueva_fecha = datetime.now() + timedelta(days=30)
        cur.execute("UPDATE usuarios SET estado = 'activo', fecha_vencimiento = %s, descuento_proximo_mes = FALSE WHERE celular = %s",
                    (nueva_fecha, data.celular))
        if usuario["referido_por"]:
            cur.execute("SELECT id FROM usuarios WHERE codigo_referido = %s", (usuario["referido_por"],))
            ref = cur.fetchone()
            if ref:
                cur.execute("UPDATE usuarios SET descuento_proximo_mes = TRUE WHERE id = %s", (ref["id"],))
        conn.commit()
        return {"mensaje": "Pago registrado. Cuenta activa 30 días más.", "monto_gs": monto, "descuento_aplicado": tiene_descuento}
    finally:
        cur.close()
        conn.close()

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
def analizar_viaje(datos: DatosViaje):
    usuario_id = None
    if datos.celular:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM usuarios WHERE celular = %s", (datos.celular,))
            u = cur.fetchone()
            if u:
                dias = (u["fecha_vencimiento"] - datetime.now()).days if u["fecha_vencimiento"] else 0
                if dias <= 0 and u["estado"] not in ["activo"]:
                    raise HTTPException(status_code=403, detail="Suscripción vencida. Renová para continuar.")
                usuario_id = u["id"]
            cur.close()
            conn.close()
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
            conn = psycopg2.connect(os.getenv("DATABASE_URL"))
            cur = conn.cursor()
            cur.execute("INSERT INTO viajes_log (usuario_id, origen, destino, distancia_km, tarifa_gs, ganancia_gs) VALUES (%s,%s,%s,%s,%s,%s)",
                        (usuario_id, datos.origen, datos.destino, datos.distancia_km, datos.tarifa_estimada_gs, calc["ganancia_neta_gs"]))
            conn.commit()
            cur.close()
            conn.close()
        except:
            pass

    return {"conviene": calc["conviene"], "veredicto": calc["veredicto"], "ganancia_neta_gs": calc["ganancia_neta_gs"],
            "resumen_voz": resumen_voz, "analisis_detallado": analisis, "alertas": calc["alertas"]}

@app.post("/registrar-decision")
def registrar_decision(data: dict):
    celular = data.get("celular")
    decision = data.get("decision")
    if not celular or not decision:
        return {"ok": True}
    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        cur = conn.cursor()
        cur.execute("SELECT id FROM usuarios WHERE celular = %s", (celular,))
        u = cur.fetchone()
        if u:
            cur.execute("UPDATE viajes_log SET decision = %s WHERE usuario_id = %s AND decision IS NULL ORDER BY created_at DESC LIMIT 1",
                        (decision, u[0]))
            conn.commit()
        cur.close()
        conn.close()
    except:
        pass
    return {"ok": True}

@app.get("/")
def root():
    return {"status": "VozViaje backend corriendo", "version": "2.0.0"}

@app.get("/health")
def health():
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    db_ok = False
    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        conn.close()
        db_ok = True
    except:
        pass
    return {"status": "ok", "ia_configurada": bool(api_key and api_key != "TU_API_KEY_AQUI"),
            "db_conectada": db_ok, "timestamp": datetime.now().isoformat()}