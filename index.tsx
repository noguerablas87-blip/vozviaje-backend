import { useState, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ScrollView, Alert, Switch, Platform
} from 'react-native';
import * as Speech from 'expo-speech';
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND_URL = 'https://vozviaje-backend-production.up.railway.app';

// Viaje de ejemplo para simular notificaciones
const VIAJES_EJEMPLO = [
  {
    pasajero_nombre: 'Carlos M.',
    pasajero_calificacion: 4.8,
    pasajero_total_viajes: 342,
    origen: 'Shopping del Sol',
    destino: 'Aeropuerto Silvio Pettirossi',
    distancia_km: 18.4,
    duracion_min: 22,
    tarifa_estimada_gs: 78000,
    hora_actual: new Date().toLocaleTimeString('es-PY', { hour: '2-digit', minute: '2-digit' }),
  },
  {
    pasajero_nombre: 'Ana G.',
    pasajero_calificacion: 3.9,
    pasajero_total_viajes: 45,
    origen: 'Villa Morra',
    destino: 'Centro Histórico',
    distancia_km: 4.2,
    duracion_min: 12,
    tarifa_estimada_gs: 22000,
    hora_actual: new Date().toLocaleTimeString('es-PY', { hour: '2-digit', minute: '2-digit' }),
  },
  {
    pasajero_nombre: 'Roberto S.',
    pasajero_calificacion: 4.5,
    pasajero_total_viajes: 180,
    origen: 'CDE - Shopping París',
    destino: 'Terminal de Ómnibus',
    distancia_km: 6.8,
    duracion_min: 15,
    tarifa_estimada_gs: 35000,
    hora_actual: new Date().toLocaleTimeString('es-PY', { hour: '2-digit', minute: '2-digit' }),
  },
];

type Viaje = typeof VIAJES_EJEMPLO[0];
type HistorialItem = {
  viaje: Viaje;
  resultado: any;
  decision: 'aceptado' | 'rechazado';
  fecha: string;
};

export default function App() {
  const [viajeActual, setViajeActual] = useState<Viaje | null>(null);
  const [resultado, setResultado] = useState<any>(null);
  const [cargando, setCargando] = useState(false);
  const [historial, setHistorial] = useState<HistorialItem[]>([]);
  const [vozActiva, setVozActiva] = useState(true);
  const [vista, setVista] = useState<'inicio' | 'viaje' | 'historial'>('inicio');

  useEffect(() => {
    cargarHistorial();
  }, []);

  const cargarHistorial = async () => {
    try {
      const data = await AsyncStorage.getItem('historial_viajes');
      if (data) setHistorial(JSON.parse(data));
    } catch {}
  };

  const guardarHistorial = async (item: HistorialItem) => {
    try {
      const nuevo = [item, ...historial].slice(0, 50);
      setHistorial(nuevo);
      await AsyncStorage.setItem('historial_viajes', JSON.stringify(nuevo));
    } catch {}
  };

  const simularViaje = async () => {
    const viaje = VIAJES_EJEMPLO[Math.floor(Math.random() * VIAJES_EJEMPLO.length)];
    viaje.hora_actual = new Date().toLocaleTimeString('es-PY', { hour: '2-digit', minute: '2-digit' });
    setViajeActual(viaje);
    setResultado(null);
    setCargando(true);
    setVista('viaje');

    try {
      const res = await fetch(`${BACKEND_URL}/analizar-viaje`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(viaje),
      });
      const data = await res.json();
      setResultado(data);
      if (vozActiva) {
        Speech.speak(data.resumen_voz, { language: 'es-PY', rate: 0.95 });
      }
    } catch (e) {
      Alert.alert('Error', 'No se pudo conectar al servidor. Verificá tu conexión.');
    } finally {
      setCargando(false);
    }
  };

  const decidir = async (decision: 'aceptado' | 'rechazado') => {
    if (!viajeActual || !resultado) return;
    const item: HistorialItem = {
      viaje: viajeActual,
      resultado,
      decision,
      fecha: new Date().toLocaleString('es-PY'),
    };
    await guardarHistorial(item);
    Speech.stop();
    if (vozActiva) {
      Speech.speak(decision === 'aceptado' ? 'Viaje aceptado. Buen viaje.' : 'Viaje rechazado.', { language: 'es-PY' });
    }
    setVista('inicio');
    setViajeActual(null);
    setResultado(null);
  };

  const colorVeredicto = (v: string) => {
    if (v === 'Conveniente') return '#1D9E75';
    if (v === 'Regular') return '#BA7517';
    return '#E24B4A';
  };

  const statsHistorial = () => {
    const aceptados = historial.filter(h => h.decision === 'aceptado').length;
    const ganancia = historial
      .filter(h => h.decision === 'aceptado')
      .reduce((acc, h) => acc + (h.resultado?.ganancia_neta_gs || 0), 0);
    return { aceptados, rechazados: historial.length - aceptados, ganancia };
  };

  if (vista === 'historial') {
    const stats = statsHistorial();
    return (
      <View style={s.container}>
        <View style={s.header}>
          <Text style={s.headerTitle}>Historial del mes</Text>
          <TouchableOpacity onPress={() => setVista('inicio')}>
            <Text style={s.linkText}>Volver</Text>
          </TouchableOpacity>
        </View>
        <View style={s.statsRow}>
          <View style={s.statCard}>
            <Text style={s.statVal}>{stats.aceptados}</Text>
            <Text style={s.statLabel}>Aceptados</Text>
          </View>
          <View style={s.statCard}>
            <Text style={s.statVal}>{stats.rechazados}</Text>
            <Text style={s.statLabel}>Rechazados</Text>
          </View>
          <View style={s.statCard}>
            <Text style={[s.statVal, { fontSize: 13 }]}>
              {(stats.ganancia / 1000).toFixed(0)}K Gs.
            </Text>
            <Text style={s.statLabel}>Ganancia</Text>
          </View>
        </View>
        <ScrollView style={{ flex: 1 }}>
          {historial.length === 0 && (
            <Text style={s.emptyText}>No hay viajes registrados aún.</Text>
          )}
          {historial.map((item, i) => (
            <View key={i} style={s.historialCard}>
              <View style={s.historialRow}>
                <Text style={s.historialNombre}>{item.viaje.pasajero_nombre}</Text>
                <View style={[s.badge, { backgroundColor: item.decision === 'aceptado' ? '#E1F5EE' : '#FCEBEB' }]}>
                  <Text style={[s.badgeText, { color: item.decision === 'aceptado' ? '#085041' : '#791F1F' }]}>
                    {item.decision}
                  </Text>
                </View>
              </View>
              <Text style={s.historialRuta}>{item.viaje.origen} → {item.viaje.destino}</Text>
              <Text style={s.historialFecha}>{item.fecha} · Gs. {item.resultado?.ganancia_neta_gs?.toLocaleString()}</Text>
            </View>
          ))}
        </ScrollView>
      </View>
    );
  }

  if (vista === 'viaje' && viajeActual) {
    return (
      <ScrollView style={s.container} contentContainerStyle={{ paddingBottom: 40 }}>
        <View style={s.header}>
          <Text style={s.headerTitle}>Nuevo viaje</Text>
          <View style={s.vozRow}>
            <Text style={s.vozLabel}>Voz</Text>
            <Switch value={vozActiva} onValueChange={setVozActiva} />
          </View>
        </View>

        <View style={s.card}>
          <Text style={s.pasajeroNombre}>{viajeActual.pasajero_nombre}</Text>
          <Text style={s.calificacion}>★ {viajeActual.pasajero_calificacion} · {viajeActual.pasajero_total_viajes} viajes</Text>

          <View style={s.divider} />

          <View style={s.dataRow}>
            <Text style={s.dataLabel}>Origen</Text>
            <Text style={s.dataVal}>{viajeActual.origen}</Text>
          </View>
          <View style={s.dataRow}>
            <Text style={s.dataLabel}>Destino</Text>
            <Text style={s.dataVal}>{viajeActual.destino}</Text>
          </View>
          <View style={s.dataRow}>
            <Text style={s.dataLabel}>Distancia</Text>
            <Text style={s.dataVal}>{viajeActual.distancia_km} km · {viajeActual.duracion_min} min</Text>
          </View>
          <View style={s.dataRow}>
            <Text style={s.dataLabel}>Tarifa</Text>
            <Text style={s.dataVal}>Gs. {viajeActual.tarifa_estimada_gs.toLocaleString()}</Text>
          </View>
        </View>

        {cargando && (
          <View style={s.cargandoBox}>
            <Text style={s.cargandoText}>Analizando viaje...</Text>
          </View>
        )}

        {resultado && !cargando && (
          <View style={s.resultadoCard}>
            <Text style={[s.veredicto, { color: colorVeredicto(resultado.veredicto) }]}>
              {resultado.veredicto}
            </Text>
            <Text style={s.ganancia}>
              Ganancia estimada: Gs. {resultado.ganancia_neta_gs?.toLocaleString()}
            </Text>
            <Text style={s.analisis}>{resultado.analisis_detallado}</Text>
            {resultado.alertas?.length > 0 && (
              <View style={s.alertaBox}>
                {resultado.alertas.map((a: string, i: number) => (
                  <Text key={i} style={s.alertaText}>⚠ {a}</Text>
                ))}
              </View>
            )}
          </View>
        )}

        {resultado && !cargando && (
          <View style={s.botonesRow}>
            <TouchableOpacity style={s.btnRechazar} onPress={() => decidir('rechazado')}>
              <Text style={s.btnRechazarText}>Rechazar</Text>
            </TouchableOpacity>
            <TouchableOpacity style={s.btnAceptar} onPress={() => decidir('aceptado')}>
              <Text style={s.btnAceptarText}>Aceptar</Text>
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>
    );
  }

  return (
    <View style={s.container}>
      <View style={s.header}>
        <Text style={s.headerTitle}>VozViaje</Text>
        <TouchableOpacity onPress={() => setVista('historial')}>
          <Text style={s.linkText}>Historial</Text>
        </TouchableOpacity>
      </View>

      <View style={s.inicioContent}>
        <Text style={s.inicioSubtitle}>Asistente de voz para conductores</Text>
        <View style={s.vozRow}>
          <Text style={s.vozLabel}>Lectura de voz automática</Text>
          <Switch value={vozActiva} onValueChange={setVozActiva} />
        </View>
        <TouchableOpacity style={s.btnSimular} onPress={simularViaje}>
          <Text style={s.btnSimularText}>Simular viaje entrante</Text>
        </TouchableOpacity>
        <Text style={s.nota}>
          En producción, esta pantalla detectará automáticamente las notificaciones de Bolt y Uber.
        </Text>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F8F8F6', paddingTop: 55 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20, paddingBottom: 16 },
  headerTitle: { fontSize: 22, fontWeight: '500', color: '#1A1A18' },
  linkText: { fontSize: 14, color: '#185FA5' },
  card: { backgroundColor: '#fff', marginHorizontal: 16, borderRadius: 12, padding: 16, borderWidth: 0.5, borderColor: '#E0E0DA', marginBottom: 12 },
  pasajeroNombre: { fontSize: 18, fontWeight: '500', color: '#1A1A18', marginBottom: 4 },
  calificacion: { fontSize: 14, color: '#5F5E5A', marginBottom: 12 },
  divider: { height: 0.5, backgroundColor: '#E0E0DA', marginBottom: 12 },
  dataRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 },
  dataLabel: { fontSize: 13, color: '#888780' },
  dataVal: { fontSize: 13, fontWeight: '500', color: '#1A1A18', maxWidth: '60%', textAlign: 'right' },
  cargandoBox: { backgroundColor: '#E1F5EE', marginHorizontal: 16, borderRadius: 8, padding: 14, marginBottom: 12 },
  cargandoText: { color: '#085041', fontSize: 14, textAlign: 'center' },
  resultadoCard: { backgroundColor: '#fff', marginHorizontal: 16, borderRadius: 12, padding: 16, borderWidth: 0.5, borderColor: '#E0E0DA', marginBottom: 12 },
  veredicto: { fontSize: 20, fontWeight: '500', marginBottom: 6 },
  ganancia: { fontSize: 15, color: '#1A1A18', marginBottom: 10 },
  analisis: { fontSize: 13, color: '#5F5E5A', lineHeight: 20 },
  alertaBox: { backgroundColor: '#FAEEDA', borderRadius: 8, padding: 10, marginTop: 10 },
  alertaText: { fontSize: 13, color: '#633806', marginBottom: 4 },
  botonesRow: { flexDirection: 'row', gap: 12, marginHorizontal: 16 },
  btnAceptar: { flex: 1, backgroundColor: '#1D9E75', borderRadius: 10, padding: 16, alignItems: 'center' },
  btnAceptarText: { color: '#fff', fontSize: 16, fontWeight: '500' },
  btnRechazar: { flex: 1, backgroundColor: '#fff', borderRadius: 10, padding: 16, alignItems: 'center', borderWidth: 0.5, borderColor: '#E0E0DA' },
  btnRechazarText: { color: '#5F5E5A', fontSize: 16 },
  inicioContent: { flex: 1, paddingHorizontal: 20, paddingTop: 20 },
  inicioSubtitle: { fontSize: 16, color: '#5F5E5A', marginBottom: 24 },
  vozRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 },
  vozLabel: { fontSize: 15, color: '#1A1A18' },
  btnSimular: { backgroundColor: '#1D9E75', borderRadius: 12, padding: 18, alignItems: 'center', marginBottom: 16 },
  btnSimularText: { color: '#fff', fontSize: 16, fontWeight: '500' },
  nota: { fontSize: 12, color: '#888780', textAlign: 'center', lineHeight: 18 },
  statsRow: { flexDirection: 'row', gap: 10, marginHorizontal: 16, marginBottom: 16 },
  statCard: { flex: 1, backgroundColor: '#F1EFE8', borderRadius: 8, padding: 12, alignItems: 'center' },
  statVal: { fontSize: 20, fontWeight: '500', color: '#1A1A18' },
  statLabel: { fontSize: 12, color: '#888780', marginTop: 2 },
  historialCard: { backgroundColor: '#fff', marginHorizontal: 16, borderRadius: 10, padding: 14, borderWidth: 0.5, borderColor: '#E0E0DA', marginBottom: 8 },
  historialRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  historialNombre: { fontSize: 14, fontWeight: '500', color: '#1A1A18' },
  historialRuta: { fontSize: 13, color: '#5F5E5A', marginBottom: 3 },
  historialFecha: { fontSize: 12, color: '#888780' },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 20 },
  badgeText: { fontSize: 11, fontWeight: '500' },
  emptyText: { textAlign: 'center', color: '#888780', marginTop: 40, fontSize: 14 },
});
