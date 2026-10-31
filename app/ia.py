"""Uso de Gemini: lectura de horarios (PDF, imagen, texto) y conversación con funciones."""
import json
import logging
import time

from google import genai
from google.genai import errors, types

from .config import settings

log = logging.getLogger("lucho.ia")
_cliente: genai.Client | None = None


def cliente() -> genai.Client:
    global _cliente
    if _cliente is None:
        _cliente = genai.Client(api_key=settings().gemini_api_key)
    return _cliente


# Errores temporales de Gemini: 429 (cuota/saturación), 500, 503 (alta demanda), 504
CODIGOS_TEMPORALES = {429, 500, 503, 504}
ESPERAS = (1, 3)  # segundos entre reintentos con el mismo modelo


def generar(contents, config):
    """Llama a Gemini con reintentos. Si el modelo principal sigue saturado,
    usa el modelo de respaldo (GEMINI_MODEL_RESPALDO)."""
    s = settings()
    modelos = [s.gemini_model] + [m for m in [s.gemini_model_respaldo] if m and m != s.gemini_model]
    ultimo_error = None
    for modelo in modelos:
        for intento in range(len(ESPERAS) + 1):
            try:
                return cliente().models.generate_content(model=modelo, contents=contents, config=config)
            except errors.APIError as e:
                if getattr(e, "code", None) not in CODIGOS_TEMPORALES:
                    raise
                ultimo_error = e
                log.warning("Gemini %s respondió %s (intento %d)", modelo, e.code, intento + 1)
                if intento < len(ESPERAS):
                    time.sleep(ESPERAS[intento])
        log.warning("Cambiando al modelo de respaldo")
    raise ultimo_error


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


def extraer(contenido: bytes | None = None, mime: str | None = None, texto: str | None = None, hoy: str = "") -> dict:
    partes = []
    if contenido:
        partes.append(types.Part.from_bytes(data=contenido, mime_type=mime))
    if texto:
        partes.append(types.Part.from_text(text=f"Texto del estudiante:\n{texto}"))
    partes.append(types.Part.from_text(text=f"Fecha de hoy: {hoy}"))
    respuesta = generar(
        contents=[types.Content(role="user", parts=partes)],
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCCION_EXTRACCION,
            response_mime_type="application/json",
            response_json_schema=ESQUEMA_EXTRACCION,
            temperature=0,
        ),
    )
    return json.loads(respuesta.text)


def corregir(borrador: dict, instruccion: str, hoy: str) -> dict:
    """Aplica una corrección en lenguaje natural ('el viernes es en el 210') a un borrador (CU-05 flujo 3a)."""
    texto = (
        "Este es el borrador actual en JSON:\n"
        + json.dumps({"tipo_documento": borrador["tipo"], "clases": borrador.get("clases", []),
                      "evaluaciones": borrador.get("evaluaciones", [])}, ensure_ascii=False)
        + f"\n\nEl estudiante pide esta corrección: {instruccion}\n"
        "Devuelve el borrador completo con la corrección aplicada y todo lo demás igual."
    )
    return extraer(texto=texto, hoy=hoy)


# ---------- Conversación con funciones ----------

def conversar(instruccion_sistema: str, historial: list[dict], mensaje: str,
              declaraciones: list[dict], ejecutar_funcion, max_pasos: int = 6) -> str:
    """Bucle de function calling: Gemini decide qué función usar, Lucho la ejecuta con datos reales
    de la base de datos y le devuelve el resultado, hasta que Gemini responde con texto."""
    contenidos = [
        types.Content(role=m["rol"], parts=[types.Part.from_text(text=m["contenido"])]) for m in historial
    ]
    contenidos.append(types.Content(role="user", parts=[types.Part.from_text(text=mensaje)]))
    config = types.GenerateContentConfig(
        system_instruction=instruccion_sistema,
        tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(name=d["name"], description=d["description"],
                                      parameters_json_schema=d["parameters"])
            for d in declaraciones
        ])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.7,
    )
    for _ in range(max_pasos):
        respuesta = generar(contents=contenidos, config=config)
        llamadas = respuesta.function_calls or []
        if not llamadas:
            return (respuesta.text or "").strip()
        # Se devuelve el contenido tal cual (incluye las firmas de razonamiento que exige Gemini 3)
        contenidos.append(respuesta.candidates[0].content)
        partes_respuesta = []
        for llamada in llamadas:
            try:
                resultado = ejecutar_funcion(llamada.name, dict(llamada.args or {}))
            except Exception as e:  # el error se le explica a la IA para que responda bien
                log.exception("Error en la función %s", llamada.name)
                resultado = {"error": f"Falló la función: {e}"}
            log.info("Función %s(%s) -> %s", llamada.name, llamada.args, str(resultado)[:300])
            partes_respuesta.append(types.Part.from_function_response(
                name=llamada.name, response={"resultado": resultado}))
        contenidos.append(types.Content(role="user", parts=partes_respuesta))
    return "Perdón, me enredé con esa solicitud. ¿Me la puedes decir de otra forma?"
