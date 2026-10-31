"""Recordatorios de parciales, entregas y notas, y sus avisos programados (CU-09, CU-10)."""
from datetime import date, datetime, time, timedelta

from . import db
from .tiempo import ahora, combinar, fecha_hora_texto, fecha_texto, hora_texto

HORA_AVISO_DIA_ANTES = time(19, 0)
HORA_AVISO_SIN_HORA = time(7, 0)
FIN_DEL_DIA = time(23, 59)


def calcular_avisos(evento: datetime, tiene_hora: bool, dias_antes: list[int] | None, momento: datetime) -> list[datetime]:
    """Avisos por defecto: el día anterior a las 7:00 p. m. y el mismo día 2 horas antes
    (o a las 7:00 a. m. si no tiene hora). `dias_antes` agrega avisos extra, p. ej. [7] = una semana antes."""
    avisos = {combinar(evento.date() - timedelta(days=1), HORA_AVISO_DIA_ANTES)}
    if tiene_hora:
        avisos.add(evento - timedelta(hours=2))
    else:
        avisos.add(combinar(evento.date(), HORA_AVISO_SIN_HORA))
    for d in dias_antes or []:
        if 1 <= d <= 60:
            avisos.add(combinar(evento.date() - timedelta(days=d), HORA_AVISO_DIA_ANTES))
    return sorted(a for a in avisos if momento < a < evento)


def crear(estudiante_id: int, titulo: str, fecha: str, hora: str | None = None, tipo: str = "nota",
          materia: str | None = None, dias_antes: list[int] | None = None, momento: datetime | None = None) -> dict:
    momento = momento or ahora()
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        return {"error": "Fecha inválida, usa el formato AAAA-MM-DD."}
    try:
        hora_t = time.fromisoformat(hora) if hora else None
    except ValueError:
        return {"error": "Hora inválida, usa el formato HH:MM en 24 horas."}
    evento = combinar(dia, hora_t or FIN_DEL_DIA)
    if evento <= momento:
        return {"error": f"La fecha {fecha_texto(dia)} ya pasó. Pregúntale al estudiante la fecha correcta."}
    if tipo not in ("parcial", "entrega", "quiz", "nota"):
        tipo = "nota"
    avisos = calcular_avisos(evento, hora_t is not None, dias_antes, momento)
    with db.conexion() as conn:
        rid = conn.execute(
            """INSERT INTO recordatorios (estudiante_id, tipo, titulo, materia, fecha_evento)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (estudiante_id, tipo, titulo, materia, evento),
        ).fetchone()["id"]
        for a in avisos:
            conn.execute("INSERT INTO avisos (recordatorio_id, enviar_at) VALUES (%s, %s)", (rid, a))
    return {
        "id": rid,
        "titulo": titulo,
        "fecha": fecha_hora_texto(evento) if hora_t else fecha_texto(dia),
        "avisos": [fecha_hora_texto(a) for a in avisos],
    }


def listar(estudiante_id: int, incluir_completados=False, momento: datetime | None = None) -> list[dict]:
    filas = db.varios(
        f"""SELECT r.id, r.tipo, r.titulo, r.materia, r.fecha_evento, r.completado
            FROM recordatorios r WHERE r.estudiante_id = %s AND r.fecha_evento > %s
            {'' if incluir_completados else 'AND NOT r.completado'}
            ORDER BY r.fecha_evento LIMIT 30""",
        (estudiante_id, momento or ahora()),
    )
    return [_publico(f) for f in filas]


def _publico(f: dict) -> dict:
    sin_hora = f["fecha_evento"].astimezone(ahora().tzinfo).time() == FIN_DEL_DIA
    return {
        "id": f["id"],
        "tipo": f["tipo"],
        "titulo": f["titulo"],
        "materia": f["materia"],
        "fecha": fecha_texto(f["fecha_evento"].astimezone(ahora().tzinfo)) if sin_hora else fecha_hora_texto(f["fecha_evento"]),
        "completado": f["completado"],
    }


def _propio(estudiante_id: int, recordatorio_id: int) -> dict | None:
    return db.uno("SELECT * FROM recordatorios WHERE id = %s AND estudiante_id = %s", (recordatorio_id, estudiante_id))


def actualizar(estudiante_id: int, recordatorio_id: int, titulo: str | None = None, fecha: str | None = None,
               hora: str | None = None, materia: str | None = None, momento: datetime | None = None) -> dict:
    actual = _propio(estudiante_id, recordatorio_id)
    if not actual:
        return {"error": "No existe ese recordatorio."}
    local = actual["fecha_evento"].astimezone(ahora().tzinfo)
    tenia_hora = local.time() != FIN_DEL_DIA
    nueva_fecha = fecha or local.date().isoformat()
    nueva_hora = hora or (local.strftime("%H:%M") if tenia_hora else None)
    eliminar(estudiante_id, recordatorio_id)
    return crear(estudiante_id, titulo or actual["titulo"], nueva_fecha, nueva_hora, actual["tipo"],
                 materia or actual["materia"], momento=momento)


def eliminar(estudiante_id: int, recordatorio_id: int) -> dict:
    n = db.ejecutar("DELETE FROM recordatorios WHERE id = %s AND estudiante_id = %s", (recordatorio_id, estudiante_id))
    return {"eliminado": bool(n)}


def completar(estudiante_id: int, recordatorio_id: int) -> dict:
    n = db.ejecutar(
        "UPDATE recordatorios SET completado = TRUE WHERE id = %s AND estudiante_id = %s", (recordatorio_id, estudiante_id))
    if n:
        db.ejecutar("UPDATE avisos SET enviado = TRUE WHERE recordatorio_id = %s AND NOT enviado", (recordatorio_id,))
    return {"completado": bool(n)}


def texto_aviso(r: dict, momento: datetime | None = None) -> str:
    """Texto del aviso que llega al estudiante."""
    from .horario import normalizar
    momento = momento or ahora()
    evento = r["fecha_evento"].astimezone(momento.tzinfo)
    hoy = momento.date()
    if evento.date() == hoy:
        dia = "hoy"
    elif evento.date() == hoy + timedelta(days=1):
        dia = "mañana"
    else:
        dia = fecha_texto(evento)
    cuando = dia if evento.time() == FIN_DEL_DIA else f"{dia} a las {hora_texto(evento.time())}"
    emoji = {"parcial": "📝", "entrega": "📤", "quiz": "❓"}.get(r["tipo"], "🔔")
    materia = r.get("materia") or ""
    materia = f" ({materia})" if materia and normalizar(materia) not in normalizar(r["titulo"]) else ""
    return f"{emoji} Recordatorio: *{r['titulo']}*{materia}\n🗓️ Es {cuando}. ¡Tú puedes! 💪"
