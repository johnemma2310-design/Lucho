"""Validación, borradores y consultas del horario (CU-02 a CU-08)."""
import json
import unicodedata
from datetime import date, datetime, time, timedelta

from . import db
from .tiempo import ahora, combinar, fecha_texto, hora_texto, nombre_dia

TIPOS_EVALUACION = ("parcial", "entrega", "quiz", "nota")


# ---------- Validación de lo que extrajo la IA ----------

def _hora(valor) -> time | None:
    if not valor:
        return None
    try:
        h, m = str(valor).strip().split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError):
        return None


def validar_clases(clases: list[dict]) -> tuple[list[dict], list[str]]:
    """Devuelve las clases válidas (normalizadas) y una lista de problemas para mostrar al estudiante."""
    validas, problemas = [], []
    for c in clases or []:
        materia = (c.get("materia") or "").strip()
        dia = c.get("dia_semana")
        inicio, fin = _hora(c.get("hora_inicio")), _hora(c.get("hora_fin"))
        if not materia:
            problemas.append("Una clase no tenía nombre de materia y la omití.")
            continue
        if not isinstance(dia, int) or not 1 <= dia <= 7:
            problemas.append(f"No entendí el día de *{materia}*.")
            continue
        if not inicio or not fin or fin <= inicio:
            problemas.append(f"Las horas de *{materia}* el {nombre_dia(dia)} no son claras.")
            continue
        validas.append({
            "materia": materia,
            "grupo": (c.get("grupo") or "").strip() or None,
            "dia_semana": dia,
            "hora_inicio": inicio.strftime("%H:%M"),
            "hora_fin": fin.strftime("%H:%M"),
            "salon": (str(c.get("salon") or "")).strip() or None,
            "bloque": (str(c.get("bloque") or "")).strip() or None,
            "docente": (c.get("docente") or "").strip() or None,
        })
    validas.sort(key=lambda c: (c["dia_semana"], c["hora_inicio"]))
    return _sin_duplicados(validas), problemas


def _sin_duplicados(clases: list[dict]) -> list[dict]:
    vistos, salida = set(), []
    for c in clases:
        clave = (c["materia"].lower(), c["dia_semana"], c["hora_inicio"])
        if clave not in vistos:
            vistos.add(clave)
            salida.append(c)
    return salida


def cruces(clases: list[dict]) -> list[tuple[dict, dict]]:
    """Pares de clases del mismo día cuyos horarios se solapan."""
    resultado = []
    for i, a in enumerate(clases):
        for b in clases[i + 1:]:
            if a["dia_semana"] == b["dia_semana"] and a["hora_inicio"] < b["hora_fin"] and b["hora_inicio"] < a["hora_fin"]:
                resultado.append((a, b))
    return resultado


def validar_evaluaciones(evaluaciones: list[dict], hoy: date) -> tuple[list[dict], list[str]]:
    validas, problemas = [], []
    for e in evaluaciones or []:
        titulo = (e.get("titulo") or "").strip()
        try:
            fecha = date.fromisoformat(str(e.get("fecha")))
        except ValueError:
            problemas.append(f"No entendí la fecha de *{titulo or 'una evaluación'}*.")
            continue
        if fecha < hoy:
            continue  # fechas ya pasadas no se recuerdan
        tipo = e.get("tipo") if e.get("tipo") in TIPOS_EVALUACION else "parcial"
        hora = _hora(e.get("hora"))
        validas.append({
            "tipo": tipo,
            "titulo": titulo or tipo.capitalize(),
            "materia": (e.get("materia") or "").strip() or None,
            "fecha": fecha.isoformat(),
            "hora": hora.strftime("%H:%M") if hora else None,
        })
    validas.sort(key=lambda e: (e["fecha"], e["hora"] or "99"))
    return validas, problemas


# ---------- Formato de mensajes ----------

def texto_clase(c: dict, con_dia=False) -> str:
    inicio = c["hora_inicio"] if isinstance(c["hora_inicio"], time) else _hora(c["hora_inicio"])
    fin = c["hora_fin"] if isinstance(c["hora_fin"], time) else _hora(c["hora_fin"])
    lugar = [f"salón {c['salon']}" if c.get("salon") else "salón por confirmar ❓"]
    if c.get("bloque"):
        lugar.append(f"bloque {c['bloque']}")
    donde = ", ".join(lugar)
    dia = f"{nombre_dia(c['dia_semana']).capitalize()} " if con_dia else ""
    return f"• {dia}{hora_texto(inicio)} – {hora_texto(fin)}: *{c['materia']}* ({donde})"


def resumen_borrador(datos: dict) -> str:
    if datos["tipo"] == "evaluaciones":
        lineas = ["Encontré estas fechas:\n"]
        for e in datos["evaluaciones"]:
            hora = f" a las {hora_texto(_hora(e['hora']))}" if e.get("hora") else ""
            materia = f" ({e['materia']})" if e.get("materia") else ""
            lineas.append(f"• {fecha_texto(date.fromisoformat(e['fecha'])).capitalize()}{hora}: *{e['titulo']}*{materia}")
    else:
        lineas = ["Esto fue lo que entendí de tu horario:"]
        dia_actual = None
        for c in datos["clases"]:
            if c["dia_semana"] != dia_actual:
                dia_actual = c["dia_semana"]
                lineas.append(f"\n*{nombre_dia(dia_actual).capitalize()}*")
            lineas.append(texto_clase(c))
        for a, b in cruces(datos["clases"]):
            lineas.append(f"\n⚠️ *{a['materia']}* y *{b['materia']}* se cruzan el {nombre_dia(a['dia_semana'])}.")
    if datos.get("problemas"):
        lineas.append("\n" + "\n".join(f"⚠️ {p}" for p in datos["problemas"]))
    return "\n".join(lineas)


# ---------- Borradores ----------

def guardar_borrador(estudiante_id: int, datos: dict, unir=False) -> dict:
    """Guarda lo extraído pendiente de confirmación. Con unir=True agrega a un borrador existente (varias fotos)."""
    if unir:
        anterior = obtener_borrador(estudiante_id)
        if anterior and anterior["tipo"] == datos["tipo"]:
            if datos["tipo"] == "horario":
                datos["clases"] = _sin_duplicados(sorted(
                    anterior["clases"] + datos["clases"], key=lambda c: (c["dia_semana"], c["hora_inicio"])))
            else:
                datos["evaluaciones"] = anterior["evaluaciones"] + datos["evaluaciones"]
            datos["problemas"] = anterior.get("problemas", []) + datos.get("problemas", [])
    db.ejecutar(
        """INSERT INTO borradores_horario (estudiante_id, datos) VALUES (%s, %s)
           ON CONFLICT (estudiante_id) DO UPDATE SET datos = EXCLUDED.datos, creado_at = now()""",
        (estudiante_id, json.dumps(datos)),
    )
    return datos


def obtener_borrador(estudiante_id: int) -> dict | None:
    fila = db.uno("SELECT datos FROM borradores_horario WHERE estudiante_id = %s", (estudiante_id,))
    return fila["datos"] if fila else None


def descartar_borrador(estudiante_id: int) -> None:
    db.ejecutar("DELETE FROM borradores_horario WHERE estudiante_id = %s", (estudiante_id,))


def contar_clases(estudiante_id: int) -> int:
    return db.uno("SELECT count(*) AS n FROM clases WHERE estudiante_id = %s", (estudiante_id,))["n"]


def confirmar_horario(estudiante_id: int, clases: list[dict], reemplazar: bool) -> int:
    with db.conexion() as conn:
        if reemplazar:
            conn.execute("DELETE FROM clases WHERE estudiante_id = %s", (estudiante_id,))
        for c in clases:
            conn.execute(
                """INSERT INTO clases (estudiante_id, materia, grupo, dia_semana, hora_inicio, hora_fin, salon, bloque, docente)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (estudiante_id, c["materia"], c.get("grupo"), c["dia_semana"], c["hora_inicio"], c["hora_fin"],
                 c.get("salon"), c.get("bloque"), c.get("docente")),
            )
        conn.execute("DELETE FROM borradores_horario WHERE estudiante_id = %s", (estudiante_id,))
    return len(clases)


# ---------- Consultas (CU-07, CU-08) ----------

def clases_del_dia(estudiante_id: int, dia_semana: int) -> list[dict]:
    return db.varios(
        "SELECT * FROM clases WHERE estudiante_id = %s AND dia_semana = %s ORDER BY hora_inicio",
        (estudiante_id, dia_semana),
    )


def dia_no_habil(fecha: date) -> str | None:
    fila = db.uno("SELECT descripcion FROM dias_no_habiles WHERE fecha = %s", (fecha,))
    return fila["descripcion"] if fila else None


def clase_actual(estudiante_id: int, momento: datetime | None = None) -> str:
    momento = momento or ahora()
    if contar_clases(estudiante_id) == 0:
        return "SIN_HORARIO: el estudiante no ha cargado su horario."
    hoy = momento.date()
    festivo = dia_no_habil(hoy)
    if not festivo:
        hora = momento.time().replace(second=0, microsecond=0)
        for c in clases_del_dia(estudiante_id, hoy.isoweekday()):
            if c["hora_inicio"] <= hora < c["hora_fin"]:
                fin = combinar(hoy, c["hora_fin"])
                minutos = int((fin - momento).total_seconds() // 60)
                return f"EN CURSO: {texto_clase(c)}. Termina en {minutos} minutos."
            if c["hora_inicio"] > hora:
                inicio = combinar(hoy, c["hora_inicio"])
                minutos = int((inicio - momento).total_seconds() // 60)
                return f"PRÓXIMA HOY: {texto_clase(c)}. Empieza en {minutos} minutos."
    # Siguiente día con clases
    for i in range(1, 15):
        dia = hoy + timedelta(days=i)
        if dia_no_habil(dia):
            continue
        clases = clases_del_dia(estudiante_id, dia.isoweekday())
        if clases:
            previo = f"Hoy es {festivo}. " if festivo else "No tiene más clases hoy. "
            return f"{previo}PRÓXIMA CLASE el {fecha_texto(dia)}: {texto_clase(clases[0])}"
    return "No se encontraron clases en los próximos 14 días."


def horario_rango(estudiante_id: int, desde: date, hasta: date) -> str:
    """Clases y pendientes entre dos fechas (incluidas), en texto para la IA."""
    if (hasta - desde).days > 13:
        hasta = desde + timedelta(days=13)
    lineas = []
    dia = desde
    while dia <= hasta:
        festivo = dia_no_habil(dia)
        clases = [] if festivo else clases_del_dia(estudiante_id, dia.isoweekday())
        pendientes = db.varios(
            """SELECT titulo, tipo, materia, fecha_evento FROM recordatorios
               WHERE estudiante_id = %s AND NOT completado
                 AND (fecha_evento AT TIME ZONE 'America/Bogota')::date = %s ORDER BY fecha_evento""",
            (estudiante_id, dia),
        )
        if clases or pendientes or festivo:
            lineas.append(f"\n{fecha_texto(dia).upper()}" + (f" ({festivo}, no hay clases)" if festivo else ""))
            lineas += [texto_clase(c) for c in clases]
            lineas += [f"• 📌 {p['tipo']}: {p['titulo']}" + (f" ({p['materia']})" if p["materia"] else "") for p in pendientes]
        dia += timedelta(days=1)
    if contar_clases(estudiante_id) == 0:
        lineas.insert(0, "AVISO: el estudiante no ha cargado su horario.")
    return "\n".join(lineas).strip() or "No hay clases ni pendientes en esas fechas."


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar nombres de materias."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def clases_de_materia(estudiante_id: int, materia: str, dia_semana: int | None = None) -> list[dict]:
    buscada = normalizar(materia)
    clases = db.varios(
        "SELECT * FROM clases WHERE estudiante_id = %s ORDER BY dia_semana, hora_inicio", (estudiante_id,))
    return [c for c in clases
            if buscada in normalizar(c["materia"]) and (dia_semana is None or c["dia_semana"] == dia_semana)]
