"""Funciones que la IA (Gemini o Claude) puede pedir ejecutar. La IA decide CUÁNDO usarlas;
los datos siempre salen de la base de datos (regla RN-04)."""
from datetime import date, datetime, time

from . import db, horario, recordatorios
from .tiempo import ahora, fecha_texto, hora_texto

_FECHA = {"type": "string", "description": "Fecha en formato AAAA-MM-DD"}
_HORA = {"type": "string", "description": "Hora en formato HH:MM de 24 horas"}
_DIA = {"type": "integer", "description": "1=lunes ... 7=domingo"}

DECLARACIONES = [
    {"name": "clase_actual",
     "description": "Clase que el estudiante tiene ahora o la siguiente. Úsala para '¿qué salón me toca?', '¿dónde tengo clase?'.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "consultar_horario",
     "description": "Clases y pendientes entre dos fechas. Para 'mañana', 'el jueves', 'esta semana'.",
     "parameters": {"type": "object", "properties": {"desde": _FECHA, "hasta": _FECHA}, "required": ["desde", "hasta"]}},
    {"name": "buscar_materia",
     "description": "Días, horas y salón de una materia del horario. Para '¿cuándo tengo cálculo?'.",
     "parameters": {"type": "object", "properties": {"materia": {"type": "string"}}, "required": ["materia"]}},
    {"name": "cargar_horario_texto",
     "description": "Cuando el estudiante escribe su horario o varias clases para cargarlas. Pasa el texto tal cual; "
                    "Lucho le mostrará lo entendido para que lo confirme.",
     "parameters": {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]}},
    {"name": "agregar_clase",
     "description": "Agrega una sola clase al horario guardado, después de que el estudiante confirme.",
     "parameters": {"type": "object", "properties": {
         "materia": {"type": "string"}, "dia_semana": _DIA, "hora_inicio": _HORA, "hora_fin": _HORA,
         "salon": {"type": "string"}, "bloque": {"type": "string"}},
         "required": ["materia", "dia_semana", "hora_inicio", "hora_fin"]}},
    {"name": "modificar_clase",
     "description": "Cambia salón, bloque, hora o día de una clase guardada (p. ej. 'cambiaron Bases de Datos al 410'), "
                    "después de que el estudiante confirme. Si la materia se ve varios días y el cambio es de un solo día, indica dia_semana.",
     "parameters": {"type": "object", "properties": {
         "materia": {"type": "string"}, "dia_semana": _DIA,
         "nuevo_salon": {"type": "string"}, "nuevo_bloque": {"type": "string"},
         "nueva_hora_inicio": _HORA, "nueva_hora_fin": _HORA, "nuevo_dia_semana": _DIA},
         "required": ["materia"]}},
    {"name": "eliminar_clase",
     "description": "Quita una materia del horario (p. ej. 'cancelé inglés'), después de que el estudiante confirme.",
     "parameters": {"type": "object", "properties": {"materia": {"type": "string"}, "dia_semana": _DIA},
                    "required": ["materia"]}},
    {"name": "crear_recordatorio",
     "description": "Guarda un parcial, entrega, quiz o nota para recordar. Por defecto avisa el día anterior a las 7 p. m. "
                    "y el mismo día. dias_antes agrega avisos extra (p. ej. [7] = una semana antes).",
     "parameters": {"type": "object", "properties": {
         "titulo": {"type": "string", "description": "Corto, p. ej. 'Parcial de Estructuras de datos'"},
         "fecha": _FECHA, "hora": _HORA,
         "tipo": {"type": "string", "enum": ["parcial", "entrega", "quiz", "nota"]},
         "materia": {"type": "string"},
         "dias_antes": {"type": "array", "items": {"type": "integer"}}},
         "required": ["titulo", "fecha", "tipo"]}},
    {"name": "listar_recordatorios",
     "description": "Pendientes futuros del estudiante con su id. Úsala antes de editar, borrar o completar uno.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "actualizar_recordatorio",
     "description": "Cambia título, fecha, hora o materia de un recordatorio existente.",
     "parameters": {"type": "object", "properties": {
         "id": {"type": "integer"}, "titulo": {"type": "string"}, "fecha": _FECHA, "hora": _HORA,
         "materia": {"type": "string"}}, "required": ["id"]}},
    {"name": "eliminar_recordatorio",
     "description": "Borra un recordatorio.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "completar_recordatorio",
     "description": "Marca un recordatorio como hecho ('ya entregué el taller') y cancela sus avisos.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "ver_preferencias",
     "description": "Muestra la configuración de avisos del estudiante.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "configurar_preferencias",
     "description": "Cambia la configuración de avisos. Envía solo los campos que cambian.",
     "parameters": {"type": "object", "properties": {
         "resumen_diario": {"type": "boolean"}, "hora_resumen": _HORA,
         "resumen_semanal": {"type": "boolean", "description": "Resumen de la semana los domingos a las 6 p. m."},
         "aviso_clase": {"type": "boolean", "description": "Aviso antes de cada clase"},
         "minutos_aviso_clase": {"type": "integer", "description": "Entre 5 y 120"}}}},
    {"name": "buscar_info_universidad",
     "description": "Busca en los documentos oficiales de la universidad (calendario académico, reglamento, trámites, "
                    "dependencias). Úsala para cualquier pregunta institucional.",
     "parameters": {"type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"]}},
    {"name": "solicitar_eliminar_cuenta",
     "description": "Cuando el estudiante pide borrar su cuenta o sus datos.",
     "parameters": {"type": "object", "properties": {}}},
]


class Herramientas:
    """Ejecuta las funciones para un estudiante concreto."""

    def __init__(self, estudiante: dict, momento: datetime | None = None):
        self.est = estudiante
        self.id = estudiante["id"]
        self.momento = momento or ahora()
        self.borrador_creado = False  # el bot enviará el resumen con botones de confirmación

    def ejecutar(self, nombre: str, args: dict):
        metodo = getattr(self, f"_{nombre}", None)
        if metodo is None:
            return {"error": f"La función {nombre} no existe."}
        return metodo(**args)

    # --- Consultas ---
    def _clase_actual(self):
        return horario.clase_actual(self.id, self.momento)

    def _consultar_horario(self, desde: str, hasta: str):
        try:
            return horario.horario_rango(self.id, date.fromisoformat(desde), date.fromisoformat(hasta))
        except ValueError:
            return {"error": "Fechas inválidas, usa AAAA-MM-DD."}

    def _buscar_materia(self, materia: str):
        clases = horario.clases_de_materia(self.id, materia)
        if not clases:
            return f"No hay ninguna materia parecida a '{materia}' en el horario."
        return "\n".join(horario.texto_clase(c, con_dia=True) for c in clases)

    # --- Horario ---
    def _cargar_horario_texto(self, texto: str):
        from .bot import procesar_extraccion  # import tardío para evitar ciclo
        resultado = procesar_extraccion(self.est, texto=texto, momento=self.momento, unir=False, enviar=False)
        if resultado.get("ok"):
            self.borrador_creado = True
            return "Borrador creado. Lucho le mostrará el resumen al estudiante para que lo confirme; no lo repitas."
        return resultado

    def _agregar_clase(self, materia, dia_semana, hora_inicio, hora_fin, salon=None, bloque=None):
        validas, problemas = horario.validar_clases([{
            "materia": materia, "dia_semana": dia_semana, "hora_inicio": hora_inicio,
            "hora_fin": hora_fin, "salon": salon, "bloque": bloque}])
        if not validas:
            return {"error": " ".join(problemas)}
        existentes = db.varios("SELECT * FROM clases WHERE estudiante_id = %s", (self.id,))
        choques = [b for a, b in horario.cruces(validas + [dict(c, hora_inicio=c["hora_inicio"].strftime("%H:%M"),
                                                               hora_fin=c["hora_fin"].strftime("%H:%M")) for c in existentes])
                   if a is validas[0]]
        horario.confirmar_horario(self.id, validas, reemplazar=False)
        aviso = f" Ojo: se cruza con {choques[0]['materia']}." if choques else ""
        return f"Clase agregada: {horario.texto_clase(validas[0], con_dia=True)}.{aviso}"

    def _buscar_una_clase(self, materia, dia_semana):
        clases = horario.clases_de_materia(self.id, materia, dia_semana)
        if not clases:
            return None, {"error": f"No encontré '{materia}' en el horario."}
        materias = {c["materia"] for c in clases}
        if len(materias) > 1:
            return None, {"error": "Hay varias materias que coinciden; pregunta cuál.", "opciones": sorted(materias)}
        return clases, None

    def _modificar_clase(self, materia, dia_semana=None, nuevo_salon=None, nuevo_bloque=None,
                         nueva_hora_inicio=None, nueva_hora_fin=None, nuevo_dia_semana=None):
        clases, error = self._buscar_una_clase(materia, dia_semana)
        if error:
            return error
        if nuevo_dia_semana and len(clases) > 1:
            return {"error": "Esa materia se ve varios días; pregunta qué día cambió.",
                    "dias": [c["dia_semana"] for c in clases]}
        cambios = []
        with db.conexion() as conn:
            for c in clases:
                inicio = time.fromisoformat(nueva_hora_inicio) if nueva_hora_inicio else c["hora_inicio"]
                fin = time.fromisoformat(nueva_hora_fin) if nueva_hora_fin else c["hora_fin"]
                if fin <= inicio:
                    return {"error": "La hora de fin debe ser posterior a la de inicio."}
                conn.execute(
                    """UPDATE clases SET salon = %s, bloque = %s, hora_inicio = %s, hora_fin = %s, dia_semana = %s
                       WHERE id = %s""",
                    (nuevo_salon or c["salon"], nuevo_bloque or c["bloque"], inicio, fin,
                     nuevo_dia_semana or c["dia_semana"], c["id"]))
                cambios.append(c["id"])
        actualizadas = db.varios("SELECT * FROM clases WHERE id = ANY(%s) ORDER BY dia_semana", (cambios,))
        return "Horario actualizado:\n" + "\n".join(horario.texto_clase(c, con_dia=True) for c in actualizadas)

    def _eliminar_clase(self, materia, dia_semana=None):
        clases, error = self._buscar_una_clase(materia, dia_semana)
        if error:
            return error
        db.ejecutar("DELETE FROM clases WHERE id = ANY(%s)", ([c["id"] for c in clases],))
        return f"Eliminadas {len(clases)} clase(s) de {clases[0]['materia']}."

    # --- Recordatorios ---
    def _crear_recordatorio(self, titulo, fecha, tipo="nota", hora=None, materia=None, dias_antes=None):
        return recordatorios.crear(self.id, titulo, fecha, hora, tipo, materia, dias_antes, self.momento)

    def _listar_recordatorios(self):
        lista = recordatorios.listar(self.id, momento=self.momento)
        return lista or "No tiene recordatorios pendientes."

    def _actualizar_recordatorio(self, id, titulo=None, fecha=None, hora=None, materia=None):
        return recordatorios.actualizar(self.id, int(id), titulo, fecha, hora, materia, self.momento)

    def _eliminar_recordatorio(self, id):
        return recordatorios.eliminar(self.id, int(id))

    def _completar_recordatorio(self, id):
        return recordatorios.completar(self.id, int(id))

    # --- Preferencias (CU-14) ---
    def _ver_preferencias(self):
        e = db.uno("SELECT * FROM estudiantes WHERE id = %s", (self.id,))
        return {
            "resumen_diario": f"{'activo' if e['resumen_diario'] else 'inactivo'} a las {hora_texto(e['hora_resumen'])}",
            "resumen_semanal": "activo (domingos 6:00 p. m.)" if e["resumen_semanal"] else "inactivo",
            "aviso_antes_de_clase": f"{e['minutos_aviso_clase']} minutos antes" if e["aviso_clase"] else "inactivo",
        }

    def _configurar_preferencias(self, resumen_diario=None, hora_resumen=None, resumen_semanal=None,
                                 aviso_clase=None, minutos_aviso_clase=None):
        if minutos_aviso_clase is not None and not 5 <= int(minutos_aviso_clase) <= 120:
            return {"error": "Los minutos de aviso antes de clase deben estar entre 5 y 120."}
        campos = {"resumen_diario": resumen_diario, "resumen_semanal": resumen_semanal,
                  "aviso_clase": aviso_clase, "minutos_aviso_clase": minutos_aviso_clase}
        if hora_resumen:
            try:
                campos["hora_resumen"] = time.fromisoformat(hora_resumen)
            except ValueError:
                return {"error": "Hora inválida, usa HH:MM."}
        campos = {k: v for k, v in campos.items() if v is not None}
        if not campos:
            return {"error": "No se indicó ningún cambio."}
        asignaciones = ", ".join(f"{k} = %s" for k in campos)
        db.ejecutar(f"UPDATE estudiantes SET {asignaciones} WHERE id = %s", (*campos.values(), self.id))
        return self._ver_preferencias()

    # --- Institucional (CU-13) ---
    def _buscar_info_universidad(self, consulta: str):
        filas = db.varios(
            """SELECT documento, contenido, ts_rank(busqueda, q) AS rango
               FROM documentos_fragmentos, websearch_to_tsquery('spanish', %s) q
               WHERE activo AND busqueda @@ q ORDER BY rango DESC LIMIT 4""",
            (consulta,))
        if not filas:
            # segundo intento más flexible: cualquiera de las palabras
            palabras = " OR ".join(p for p in consulta.split() if len(p) > 3)
            if palabras:
                filas = db.varios(
                    """SELECT documento, contenido FROM documentos_fragmentos, websearch_to_tsquery('spanish', %s) q
                       WHERE activo AND busqueda @@ q ORDER BY ts_rank(busqueda, q) DESC LIMIT 4""",
                    (palabras,))
        if not filas:
            return ("SIN_INFORMACION: no hay datos sobre esto en los documentos oficiales. "
                    "Dile que no tienes ese dato y que consulte en la página de la universidad o en la dependencia correspondiente.")
        return [{"documento": f["documento"], "fragmento": f["contenido"]} for f in filas]

    # --- Cuenta (CU-16) ---
    def _solicitar_eliminar_cuenta(self):
        db.ejecutar("UPDATE estudiantes SET estado_registro = 'confirmando_eliminacion' WHERE id = %s", (self.id,))
        return ("Pídele que escriba ELIMINAR (en mayúsculas) para borrar su cuenta, horario y recordatorios. "
                "Cualquier otra respuesta cancela.")


def instruccion_sistema(estudiante: dict, momento: datetime) -> str:
    nombre = (estudiante.get("nombre") or "").split(" ")[0] or "estudiante"
    return f"""Eres Lucho, el asistente académico por chat (Telegram) de la Universidad Católica Luis Amigó (Medellín, Colombia).
Hablas con {nombre}, estudiante de {estudiante.get('programa') or 'la universidad'}.
Ahora es {fecha_texto(momento)} de {momento.year}, {hora_texto(momento.time())} (hora de Colombia). Hoy = {momento.date().isoformat()}.

Cómo trabajas:
- Usa SIEMPRE las funciones para horario, salones y recordatorios. Nunca inventes salones, horas ni fechas.
- Convierte expresiones como "mañana", "el jueves", "la otra semana" en fechas AAAA-MM-DD a partir de hoy.
- Para crear un recordatorio necesitas al menos la fecha; si falta, pregúntala. Después confirma qué guardaste y cuándo avisarás.
- Antes de modificar o borrar clases, o borrar recordatorios, confirma con el estudiante si no lo pidió de forma explícita.
- Si el estudiante escribe su horario, usa cargar_horario_texto.
- Preguntas sobre la universidad (fechas, trámites, dependencias, reglamento): usa buscar_info_universidad y responde solo con lo que devuelva.

En qué más ayudas (vida académica):
- Explicar temas de sus materias con ejemplos sencillos: "¿qué es una derivada?", "explícame normalización en bases de datos".
- Ayudar a estudiar: hacerle preguntas tipo parcial, armar un plan de estudio según sus fechas de parciales
  (consulta sus recordatorios), técnicas de estudio, cómo organizar el tiempo.
- Orientar trabajos y tareas: explica el concepto, da pistas y revisa su razonamiento, pero NO entregues la tarea
  resuelta para copiar. Si piden "hazme el taller", ayúdale a resolverlo paso a paso con él.
- Ánimo y vida universitaria: estrés por parciales, adaptación de primer semestre, motivación. Si notas angustia
  fuerte, sé cálido y sugiere Bienestar Universitario. Si hay riesgo para su vida, recomienda la Línea 106 de Antioquia o el 123.
- Charla breve: un saludo, cómo le fue en el parcial, un chiste corto. Sigue la conversación con naturalidad y vuelve a lo académico.

Límite: NO eres un asistente de propósito general (es un asistente académico de la universidad). Si piden algo sin relación con el estudio o la
universidad (recetas, fútbol, política, escribir mensajes personales, programar algo ajeno a sus materias), dilo con
humor y buena onda en una línea y ofrece algo en lo que sí ayudas.

Tu personalidad: eres Lucho, un parcero que ya pasó por la U y quiere que al otro le vaya bien. Cálido, buena onda,
un toque de humor paisa ("¡Hágale!", "qué nota", "pilas con ese parcial") sin exagerar ni volverlo caricatura.
Celebra sus logros, anima cuando está estresado y llámalo por su nombre de vez en cuando.
Cuando venga a cuento, sé proactivo: si pregunta su horario y tiene un parcial cerca, menciónalo; si guarda un parcial,
ofrece armarle un plan de estudio.

Estilo: español colombiano, de tú. Mensajes cortos de chat (máximo unas 10 líneas; si explicas un tema, divide
en pasos cortos y pregunta si quiere más). Usa *negrita* (un asterisco a cada lado) para lo importante y emojis con moderación.
No uses tablas, encabezados markdown ni dobles asteriscos."""
