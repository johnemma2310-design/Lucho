"""Tareas automáticas: avisos de recordatorios, avisos antes de clase y resúmenes (CU-11, CU-12).
Se revisa cada minuto. Cada envío queda registrado para no repetirlo."""
import logging
from datetime import datetime, timedelta

from . import db, horario, recordatorios
from .tiempo import ahora, combinar, fecha_texto
from .canales import enviar_aviso

log = logging.getLogger("lucho.programador")
MAX_INTENTOS = 3


def revisar(momento: datetime | None = None) -> dict:
    """Ejecuta todos los envíos pendientes. Devuelve cuántos se mandaron de cada tipo (útil en pruebas)."""
    momento = momento or ahora()
    return {
        "recordatorios": enviar_recordatorios(momento),
        "clases": enviar_avisos_clase(momento),
        "resumen_diario": enviar_resumenes_diarios(momento),
        "resumen_semanal": enviar_resumenes_semanales(momento),
    }


def _reclamar(estudiante_id: int, tipo: str, clave: str) -> bool:
    """Marca un envío como hecho; devuelve False si ya se había hecho (evita duplicados)."""
    fila = db.uno(
        """INSERT INTO envios_log (estudiante_id, tipo, clave) VALUES (%s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING 1 AS ok""", (estudiante_id, tipo, clave))
    return fila is not None


# ---------- CU-11: avisos de recordatorios ----------

def enviar_recordatorios(momento: datetime) -> int:
    enviados = 0
    with db.conexion() as conn:
        pendientes = conn.execute(
            """SELECT a.id AS aviso_id, a.intentos, r.*, e.telefono, e.ultimo_mensaje_at
               FROM avisos a JOIN recordatorios r ON r.id = a.recordatorio_id
               JOIN estudiantes e ON e.id = r.estudiante_id
               WHERE NOT a.enviado AND a.enviar_at <= %s AND a.intentos < %s
                 AND NOT r.completado AND r.fecha_evento > %s AND e.estado_registro = 'activo'
               ORDER BY a.enviar_at FOR UPDATE OF a SKIP LOCKED LIMIT 100""",
            (momento, MAX_INTENTOS, momento)).fetchall()
        for p in pendientes:
            try:
                enviar_aviso(p, recordatorios.texto_aviso(p, momento), momento)
                conn.execute("UPDATE avisos SET enviado = TRUE WHERE id = %s", (p["aviso_id"],))
                enviados += 1
            except Exception:
                log.exception("No se pudo enviar el aviso %s", p["aviso_id"])
                # se reintenta en 2 minutos, máximo 3 veces
                conn.execute("UPDATE avisos SET intentos = intentos + 1, enviar_at = %s WHERE id = %s",
                             (momento + timedelta(minutes=2), p["aviso_id"]))
        # Avisos cuyo evento ya pasó: se cierran sin enviar
        conn.execute(
            """UPDATE avisos SET enviado = TRUE FROM recordatorios r
               WHERE avisos.recordatorio_id = r.id AND NOT avisos.enviado AND r.fecha_evento <= %s""", (momento,))
    return enviados


# ---------- Aviso antes de clase ----------

def enviar_avisos_clase(momento: datetime) -> int:
    hoy = momento.date()
    if horario.dia_no_habil(hoy):
        return 0
    hora = momento.time().replace(second=0, microsecond=0)
    clases = db.varios(
        """SELECT c.*, e.telefono, e.ultimo_mensaje_at, e.minutos_aviso_clase
           FROM clases c JOIN estudiantes e ON e.id = c.estudiante_id
           WHERE e.aviso_clase AND e.estado_registro = 'activo' AND c.dia_semana = %s
             AND c.hora_inicio > %s
             AND c.hora_inicio <= (%s::time + make_interval(mins => e.minutos_aviso_clase))""",
        (hoy.isoweekday(), hora, hora))
    enviados = 0
    for c in clases:
        if not _reclamar(c["estudiante_id"], "clase", f"{c['id']}:{hoy.isoformat()}"):
            continue
        minutos = int((combinar(hoy, c["hora_inicio"]) - momento).total_seconds() // 60)
        lugar = " ".join(x for x in [f"salón *{c['salon']}*" if c["salon"] else "", f"bloque {c['bloque']}" if c["bloque"] else ""] if x)
        texto = f"⏰ En {minutos} minutos tienes *{c['materia']}*" + (f" en el {lugar}" if lugar else "") + "."
        try:
            enviar_aviso(c, texto, momento)
            enviados += 1
        except Exception:
            log.exception("No se pudo avisar la clase %s", c["id"])
    return enviados


# ---------- CU-12: resúmenes ----------

def texto_resumen_dia(estudiante_id: int, momento: datetime) -> str | None:
    hoy = momento.date()
    clases = horario.clases_del_dia(estudiante_id, hoy.isoweekday())
    proximos = db.varios(
        """SELECT * FROM recordatorios WHERE estudiante_id = %s AND NOT completado
           AND fecha_evento > %s AND fecha_evento < %s ORDER BY fecha_evento""",
        (estudiante_id, momento, combinar(hoy + timedelta(days=4), datetime.min.time())))
    if not clases and not proximos:
        return None  # no se manda nada para no molestar
    lineas = [f"☀️ ¡Buenos días! Esto tienes hoy, {fecha_texto(hoy)}:"]
    if clases:
        lineas += [horario.texto_clase(c) for c in clases]
    else:
        lineas.append("• Hoy no tienes clases.")
    if proximos:
        lineas.append("\n📌 *Próximos días:*")
        for r in proximos:
            lineas.append(f"• {recordatorios._publico(r)['fecha']}: {r['titulo']}")
    return "\n".join(lineas)


def enviar_resumenes_diarios(momento: datetime) -> int:
    hoy = momento.date()
    if horario.dia_no_habil(hoy):
        return 0
    estudiantes = db.varios(
        """SELECT * FROM estudiantes WHERE resumen_diario AND estado_registro = 'activo' AND hora_resumen <= %s
           AND hora_resumen > %s::time - interval '3 hours'""",
        (momento.time(), momento.time()))
    enviados = 0
    for e in estudiantes:
        if not _reclamar(e["id"], "resumen_diario", hoy.isoformat()):
            continue
        texto = texto_resumen_dia(e["id"], momento)
        if texto:
            try:
                enviar_aviso(e, texto, momento)
                enviados += 1
            except Exception:
                log.exception("No se pudo enviar el resumen a %s", e["id"])
    return enviados


def enviar_resumenes_semanales(momento: datetime) -> int:
    if momento.isoweekday() != 7 or momento.hour < 18:
        return 0  # domingos desde las 6:00 p. m.
    lunes = momento.date() + timedelta(days=1)
    estudiantes = db.varios("SELECT * FROM estudiantes WHERE resumen_semanal AND estado_registro = 'activo'")
    enviados = 0
    for e in estudiantes:
        if not _reclamar(e["id"], "resumen_semanal", lunes.isoformat()):
            continue
        detalle = horario.horario_rango(e["id"], lunes, lunes + timedelta(days=5))
        try:
            enviar_aviso(e, f"🗓️ Tu semana desde el {fecha_texto(lunes)}:\n{detalle}", momento)
            enviados += 1
        except Exception:
            log.exception("No se pudo enviar el resumen semanal a %s", e["id"])
    return enviados
