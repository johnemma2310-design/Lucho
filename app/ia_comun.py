"""Piezas que comparten los proveedores de IA (Gemini y Claude): el esquema de lectura de horarios,
sus instrucciones y la forma segura de ejecutar las funciones que pide la IA."""
import logging

log = logging.getLogger("lucho.ia")

NO_ENTENDI = "Perdón, me enredé con esa solicitud. ¿Me la puedes decir de otra forma?"

# ---------- Extracción estructurada (CU-02, CU-03, CU-04, CU-09 flujo 1a) ----------

ESQUEMA_EXTRACCION = {
    "type": "object",
    "properties": {
        "tipo_documento": {
            "type": "string",
            "enum": ["horario", "evaluaciones", "otro"],
            "description": "horario = clases semanales; evaluaciones = fechas de parciales o entregas; otro = nada de eso.",
        },
        "confianza": {"type": "string", "enum": ["alta", "media", "baja"],
                      "description": "baja si la imagen está borrosa, cortada o es difícil de leer."},
        "clases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "materia": {"type": "string"},
                    "grupo": {"type": "string"},
                    "dia_semana": {"type": "integer", "description": "1=lunes, 2=martes, ... 6=sábado, 7=domingo"},
                    "hora_inicio": {"type": "string", "description": "HH:MM en formato 24 horas"},
                    "hora_fin": {"type": "string", "description": "HH:MM en formato 24 horas"},
                    "salon": {"type": "string", "description": "Solo el número o nombre del salón, p. ej. 305 o Sala de cómputo 5"},
                    "bloque": {"type": "string", "description": "Solo el número o nombre del bloque"},
                    "docente": {"type": "string"},
                },
                "required": ["materia", "dia_semana", "hora_inicio", "hora_fin"],
            },
        },
        "evaluaciones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["parcial", "entrega", "quiz", "nota"]},
                    "titulo": {"type": "string", "description": "p. ej. Primer parcial, Taller 2"},
                    "materia": {"type": "string"},
                    "fecha": {"type": "string", "description": "AAAA-MM-DD"},
                    "hora": {"type": "string", "description": "HH:MM 24 horas, vacío si no se indica"},
                },
                "required": ["tipo", "titulo", "fecha"],
            },
        },
        "observaciones": {"type": "string",
                          "description": "Algo que el estudiante deba saber, en una frase. Vacío si no hay nada."},
    },
    "required": ["tipo_documento", "confianza", "clases", "evaluaciones"],
}

INSTRUCCION_EXTRACCION = """Eres un extractor de datos académicos de la Universidad Católica Luis Amigó (Medellín, Colombia).
Lee el contenido y devuelve SOLO lo que aparece en él, sin inventar datos.

Reglas:
- Si es un horario de clases, llena "clases": una entrada por cada día y franja. Si una materia se ve lunes y miércoles, son dos entradas.
- Abreviaturas de días: LU/L=1, MA/M=2, MI/X=3, JU/J=4, VI/V=5, SA/S=6, DO/D=7.
- Convierte horas a formato 24 h (2 p. m. = 14:00). Si solo dice "de 8 a 10" en contexto universitario, asume 08:00 a 10:00.
- Separa salón y bloque: "B2-305", "Bloque 2 - 305" o "305 del bloque 2" => bloque "2", salón "305".
- Si un dato no aparece (salón, docente, grupo), déjalo vacío; no lo adivines.
- Si son fechas de parciales, quices o entregas (por ejemplo, un programa de curso), llena "evaluaciones".
  El año actual y la fecha de hoy te los doy abajo; úsalos para completar fechas sin año.
- Si no es ninguna de las dos cosas, tipo_documento = "otro"."""


def ejecutar_funcion_segura(ejecutar_funcion, nombre: str, argumentos: dict):
    """Ejecuta la función que pidió la IA. Si falla, le devuelve el error a la IA para que responda bien."""
    try:
        resultado = ejecutar_funcion(nombre, argumentos)
    except Exception as e:
        log.exception("Error en la función %s", nombre)
        resultado = {"error": f"Falló la función: {e}"}
    log.info("Función %s(%s) -> %s", nombre, argumentos, str(resultado)[:300])
    return resultado
