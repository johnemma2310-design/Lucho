"""Punto único de acceso al canal de mensajería (Telegram o WhatsApp).

El resto del código (bot, registro, programador) solo habla con `canal()` y nunca con una
API concreta. Cada canal implementa la misma interfaz:

    enviar_texto(destino, texto)
    enviar_botones(destino, texto, [(id_boton, titulo), ...])
    enviar_plantilla(destino, texto)      # solo WhatsApp lo necesita de verdad
    descargar_media(media_id) -> (bytes, mime)
    ventana_24h: bool                     # True si el canal limita mensajes iniciados por el bot

Así se cambia de canal con la variable CANAL del .env, y el simulador y las pruebas
pueden usar un canal falso.
"""
from datetime import timedelta

from .config import settings
from .tiempo import ahora

_canal = None


def canal():
    global _canal
    if _canal is None:
        if settings().canal == "whatsapp":
            from .whatsapp import CanalWhatsApp
            _canal = CanalWhatsApp()
        else:
            from .telegram import CanalTelegram
            _canal = CanalTelegram()
    return _canal


def usar_canal(nuevo) -> None:
    """Reemplaza el canal (simulador de consola, pruebas)."""
    global _canal
    _canal = nuevo


def enviar_aviso(estudiante: dict, texto: str, momento=None) -> None:
    """Mensaje que inicia Lucho (recordatorios, resúmenes).

    En WhatsApp, si el estudiante no escribió en las últimas 24 horas, se exige una
    plantilla aprobada (regla RN-07). Telegram no tiene esa restricción.
    """
    c = canal()
    ultimo = estudiante.get("ultimo_mensaje_at")
    dentro_de_ventana = ultimo and (momento or ahora()) - ultimo < timedelta(hours=23, minutes=50)
    if not getattr(c, "ventana_24h", False) or dentro_de_ventana:
        c.enviar_texto(estudiante["telefono"], texto)
    else:
        c.enviar_plantilla(estudiante["telefono"], texto)
