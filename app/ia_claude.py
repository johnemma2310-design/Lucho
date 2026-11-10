"""Proveedor Claude (Anthropic): lectura de horarios y conversación con herramientas (tool use).

- Lectura de horarios: Claude recibe el PDF o la imagen y se le obliga a responder llamando a la
  herramienta `guardar_datos_academicos`, cuyo esquema es ESQUEMA_EXTRACCION. Así la respuesta
  siempre llega como un dict con la forma correcta.
- Conversación: las mismas funciones de herramientas.py se le ofrecen a Claude como herramientas.
  Claude pide una, Lucho la ejecuta contra la base de datos y le devuelve el resultado.
"""
import base64
import json
import logging
import time

import anthropic

from .config import settings
from .ia_comun import ESQUEMA_EXTRACCION, INSTRUCCION_EXTRACCION, NO_ENTENDI, ejecutar_funcion_segura

log = logging.getLogger("lucho.ia")
_cliente: anthropic.Anthropic | None = None

HERRAMIENTA_EXTRACCION = "guardar_datos_academicos"
TIPOS_IMAGEN = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_TOKENS_EXTRACCION = 8000   # un horario largo puede tener muchas clases
MAX_TOKENS_CONVERSACION = 1500

# Errores temporales: 429 (límite de uso), 500/502/503/504 y 529 (Claude saturado)
CODIGOS_TEMPORALES = {429, 500, 502, 503, 504, 529}
ESPERAS = (1, 3)  # segundos entre reintentos con el mismo modelo


def cliente() -> anthropic.Anthropic:
    global _cliente
    if _cliente is None:
        # Los reintentos los maneja generar(), para poder cambiar al modelo de respaldo
        _cliente = anthropic.Anthropic(api_key=settings().anthropic_api_key, max_retries=0, timeout=90)
    return _cliente


def _es_temporal(error: anthropic.APIError) -> bool:
    if isinstance(error, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    return getattr(error, "status_code", None) in CODIGOS_TEMPORALES


def generar(**datos):
    """Llama a Claude con reintentos. Si el modelo principal sigue saturado,
    usa el modelo de respaldo (CLAUDE_MODEL_RESPALDO)."""
    s = settings()
    modelos = [s.claude_model] + [m for m in [s.claude_model_respaldo] if m and m != s.claude_model]
    ultimo_error = None
    for modelo in modelos:
        for intento in range(len(ESPERAS) + 1):
            try:
                return cliente().messages.create(model=modelo, **datos)
            except anthropic.APIError as e:
                if not _es_temporal(e):
                    raise
                ultimo_error = e
                log.warning("Claude %s respondió %s (intento %d)", modelo,
                            getattr(e, "status_code", "sin conexión"), intento + 1)
                if intento < len(ESPERAS):
                    time.sleep(ESPERAS[intento])
        log.warning("Cambiando al modelo de respaldo")
    raise ultimo_error


# ---------- Lectura de horarios ----------

def _bloque_archivo(contenido: bytes, mime: str | None) -> dict:
    datos = base64.standard_b64encode(contenido).decode("ascii")
    if mime == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": datos}}
    if mime in TIPOS_IMAGEN:
        return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": datos}}
    raise ValueError(f"Claude no puede leer archivos de tipo {mime!r}; envía un PDF, JPG, PNG, GIF o WEBP.")


def extraer(contenido: bytes | None = None, mime: str | None = None, texto: str | None = None, hoy: str = "") -> dict:
    partes = []
    if contenido:
        partes.append(_bloque_archivo(contenido, mime))
    if texto:
        partes.append({"type": "text", "text": f"Texto del estudiante:\n{texto}"})
    partes.append({"type": "text", "text": f"Fecha de hoy: {hoy}"})
    respuesta = generar(
        max_tokens=MAX_TOKENS_EXTRACCION,
        system=INSTRUCCION_EXTRACCION,
        messages=[{"role": "user", "content": partes}],
        tools=[{"name": HERRAMIENTA_EXTRACCION,
                "description": "Guarda lo que se leyó del documento o del texto del estudiante.",
                "input_schema": ESQUEMA_EXTRACCION}],
        tool_choice={"type": "tool", "name": HERRAMIENTA_EXTRACCION},
    )
    for bloque in respuesta.content:
        if bloque.type == "tool_use" and bloque.name == HERRAMIENTA_EXTRACCION:
            return dict(bloque.input)
    raise ValueError("Claude no devolvió los datos leídos")


# ---------- Conversación con herramientas ----------

def _mensajes(historial: list[dict], mensaje: str) -> list[dict]:
    """Convierte el historial de Lucho ("user" / "model") al formato de Claude ("user" / "assistant").
    Claude exige que los turnos se alternen, así que dos seguidos del mismo rol se unen."""
    mensajes: list[dict] = []
    for rol, texto in [(m["rol"], m["contenido"]) for m in historial] + [("user", mensaje)]:
        rol = "assistant" if rol in ("model", "assistant") else "user"
        if not texto:
            continue
        if mensajes and mensajes[-1]["role"] == rol:
            mensajes[-1]["content"] += "\n\n" + texto
        else:
            mensajes.append({"role": rol, "content": texto})
    while mensajes and mensajes[0]["role"] != "user":  # debe empezar el estudiante
        mensajes.pop(0)
    return mensajes


def conversar(instruccion_sistema: str, historial: list[dict], mensaje: str,
              declaraciones: list[dict], ejecutar_funcion, max_pasos: int = 6) -> str:
    mensajes = _mensajes(historial, mensaje)
    herramientas = [{"name": d["name"], "description": d["description"], "input_schema": d["parameters"]}
                    for d in declaraciones]
    for _ in range(max_pasos):
        respuesta = generar(max_tokens=MAX_TOKENS_CONVERSACION, system=instruccion_sistema,
                            messages=mensajes, tools=herramientas)
        llamadas = [b for b in respuesta.content if b.type == "tool_use"]
        if not llamadas:
            return "".join(b.text for b in respuesta.content if b.type == "text").strip()
        # Se devuelve el turno de Claude tal cual y, después, el resultado de cada herramienta
        mensajes.append({"role": "assistant", "content": respuesta.content})
        resultados = []
        for llamada in llamadas:
            resultado = ejecutar_funcion_segura(ejecutar_funcion, llamada.name, dict(llamada.input or {}))
            resultados.append({"type": "tool_result", "tool_use_id": llamada.id,
                               "content": json.dumps({"resultado": resultado}, ensure_ascii=False, default=str)})
        mensajes.append({"role": "user", "content": resultados})
    return NO_ENTENDI
