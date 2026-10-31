"""Envío y recepción de mensajes con la WhatsApp Cloud API oficial de Meta.

Se activa con CANAL=whatsapp en el .env. El resto del código no llama a Meta
directamente, sino a `canales.canal()`.
"""
import hashlib
import hmac
import logging
import re
import httpx

from .config import settings

log = logging.getLogger("lucho.whatsapp")
LIMITE_TEXTO = 4000  # WhatsApp permite 4096 caracteres por mensaje


class CanalWhatsApp:
    ventana_24h = True  # WhatsApp exige plantilla fuera de la ventana de 24 horas

    def __init__(self):
        s = settings()
        self.base = f"https://graph.facebook.com/{s.whatsapp_api_version}"
        self.headers = {"Authorization": f"Bearer {s.whatsapp_token}"}
        self.phone_id = s.whatsapp_phone_number_id

    def _post(self, payload: dict) -> dict:
        r = httpx.post(f"{self.base}/{self.phone_id}/messages", json=payload, headers=self.headers, timeout=20)
        if r.status_code >= 400:
            log.error("Error de WhatsApp %s: %s", r.status_code, r.text)
            r.raise_for_status()
        return r.json()

    def enviar_texto(self, telefono: str, texto: str) -> None:
        for parte in _partir(texto):
            self._post({
                "messaging_product": "whatsapp",
                "to": telefono,
                "type": "text",
                "text": {"body": parte, "preview_url": False},
            })

    def enviar_botones(self, telefono: str, texto: str, botones: list[tuple[str, str]]) -> None:
        """Hasta 3 botones de respuesta; cada título máximo 20 caracteres."""
        self._post({
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": texto[:1024]},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": titulo[:20]}} for bid, titulo in botones[:3]
                ]},
            },
        })

    def enviar_plantilla(self, telefono: str, parametro: str) -> None:
        """Mensaje iniciado por el bot fuera de la ventana de 24 horas (regla RN-07)."""
        s = settings()
        self._post({
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "template",
            "template": {
                "name": s.plantilla_aviso,
                "language": {"code": s.plantilla_idioma},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": _limpiar_parametro(parametro)}],
                }],
            },
        })

    def descargar_media(self, media_id: str) -> tuple[bytes, str]:
        info = httpx.get(f"{self.base}/{media_id}", headers=self.headers, timeout=20)
        info.raise_for_status()
        datos = info.json()
        archivo = httpx.get(datos["url"], headers=self.headers, timeout=60, follow_redirects=True)
        archivo.raise_for_status()
        return archivo.content, datos.get("mime_type", "application/octet-stream")


def firma_valida(cuerpo: bytes, firma_cabecera: str | None) -> bool:
    """Valida la cabecera X-Hub-Signature-256 que Meta añade a cada webhook (RNF-06)."""
    secreto = settings().whatsapp_app_secret
    if not secreto:
        return True  # modo desarrollo
    if not firma_cabecera or not firma_cabecera.startswith("sha256="):
        return False
    esperada = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma_cabecera.removeprefix("sha256="))


def _partir(texto: str) -> list[str]:
    if len(texto) <= LIMITE_TEXTO:
        return [texto]
    partes, actual = [], ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > LIMITE_TEXTO:
            partes.append(actual)
            actual = ""
        actual += linea + "\n"
    if actual.strip():
        partes.append(actual)
    return partes


def _limpiar_parametro(texto: str) -> str:
    """Los parámetros de plantilla no admiten saltos de línea, tabulaciones ni más de 4 espacios seguidos."""
    texto = re.sub(r"\s*\n+\s*", " · ", texto.strip())
    texto = re.sub(r"[\t ]{2,}", " ", texto)
    return texto[:1000]
