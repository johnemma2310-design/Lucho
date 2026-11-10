"""IA de Lucho: lectura de horarios (PDF, imagen, texto) y conversación con funciones.

Lucho puede usar Gemini (Google) o Claude (Anthropic). Se elige con IA_PROVEEDOR en el .env:
    IA_PROVEEDOR=gemini   -> app/ia_gemini.py  (GEMINI_API_KEY)
    IA_PROVEEDOR=claude   -> app/ia_claude.py  (ANTHROPIC_API_KEY)
El resto del bot no sabe cuál se está usando: solo llama extraer(), corregir() y conversar().
"""
import json

from .config import settings
from .ia_comun import ESQUEMA_EXTRACCION, INSTRUCCION_EXTRACCION  # noqa: F401  (se reexportan)

PROVEEDORES = ("gemini", "claude")


def nombre_proveedor() -> str:
    nombre = (settings().ia_proveedor or "").strip().lower()
    if nombre not in PROVEEDORES:
        raise ValueError(f"IA_PROVEEDOR={nombre!r} no existe. Usa 'gemini' o 'claude' en el .env.")
    return nombre


def proveedor():
    """Devuelve el módulo del proveedor elegido. Se importa solo el que se usa,
    así no hace falta instalar la librería del otro."""
    if nombre_proveedor() == "claude":
        from . import ia_claude as modulo
    else:
        from . import ia_gemini as modulo
    return modulo


def descripcion() -> str:
    """Texto para el log de arranque, p. ej. 'claude (claude-haiku-5-5, respaldo claude-sonnet-5-5)'."""
    s = settings()
    nombre = nombre_proveedor()
    principal, respaldo = ((s.claude_model, s.claude_model_respaldo) if nombre == "claude"
                           else (s.gemini_model, s.gemini_model_respaldo))
    return f"{nombre} ({principal}" + (f", respaldo {respaldo})" if respaldo else ")")


def falta_clave() -> str | None:
    """Nombre de la variable que falta en el .env para el proveedor elegido, o None si está todo."""
    s = settings()
    if nombre_proveedor() == "claude":
        return None if s.anthropic_api_key else "ANTHROPIC_API_KEY"
    return None if s.gemini_api_key else "GEMINI_API_KEY"


def extraer(contenido: bytes | None = None, mime: str | None = None, texto: str | None = None, hoy: str = "") -> dict:
    """Lee un horario o fechas de evaluaciones y devuelve un dict con la forma de ESQUEMA_EXTRACCION."""
    return proveedor().extraer(contenido=contenido, mime=mime, texto=texto, hoy=hoy)


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


def conversar(instruccion_sistema: str, historial: list[dict], mensaje: str,
              declaraciones: list[dict], ejecutar_funcion, max_pasos: int = 6) -> str:
    """Bucle de llamado de funciones: la IA decide qué función usar, Lucho la ejecuta con datos reales
    de la base de datos y le devuelve el resultado, hasta que la IA responde con texto.
    `historial` es una lista de {"rol": "user" | "model", "contenido": texto}."""
    return proveedor().conversar(instruccion_sistema, historial, mensaje, declaraciones, ejecutar_funcion, max_pasos)
