"""Proveedor Gemini (Google): lectura de horarios con salida JSON y conversación con funciones."""
import json
import logging
import time

from google import genai
from google.genai import errors, types

from .config import settings
from .ia_comun import ESQUEMA_EXTRACCION, INSTRUCCION_EXTRACCION, NO_ENTENDI, ejecutar_funcion_segura

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


def conversar(instruccion_sistema: str, historial: list[dict], mensaje: str,
              declaraciones: list[dict], ejecutar_funcion, max_pasos: int = 6) -> str:
    contenidos = [
        types.Content(role="model" if m["rol"] in ("model", "assistant") else "user",
                      parts=[types.Part.from_text(text=m["contenido"])])
        for m in historial
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
            resultado = ejecutar_funcion_segura(ejecutar_funcion, llamada.name, dict(llamada.args or {}))
            partes_respuesta.append(types.Part.from_function_response(
                name=llamada.name, response={"resultado": resultado}))
        contenidos.append(types.Content(role="user", parts=partes_respuesta))
    return NO_ENTENDI
