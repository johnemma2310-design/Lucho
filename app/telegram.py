"""Canal Telegram: envío de mensajes con la Bot API y lectura de las actualizaciones.

Cada estudiante se identifica como "tg:<chat_id>" en la columna `telefono`, para no chocar
con los números de WhatsApp si algún día se usan los dos canales.
"""
import html
import logging
import re

import httpx

from .config import settings

log = logging.getLogger("lucho.telegram")
LIMITE_TEXTO = 4000  # Telegram permite 4096 caracteres
PREFIJO = "tg:"


def chat_id(destino: str) -> str:
    return destino.removeprefix(PREFIJO)


def a_html(texto: str) -> str:
    """Convierte el formato estilo WhatsApp (*negrita*, _cursiva_) a HTML de Telegram,
    escapando lo demás. No toca guiones bajos dentro de palabras ni de correos."""
    t = html.escape(texto, quote=False)
    t = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w])_([^_\n]+?)_(?![\w])", r"<i>\1</i>", t)
    return t


def partir(texto: str) -> list[str]:
    if len(texto) <= LIMITE_TEXTO:
        return [texto]
    partes, actual = [], ""
    for linea in texto.split("\n"):
        if actual and len(actual) + len(linea) + 1 > LIMITE_TEXTO:
            partes.append(actual)
            actual = ""
        actual += linea + "\n"
    if actual.strip():
        partes.append(actual)
    return partes


class CanalTelegram:
    ventana_24h = False

    def __init__(self, token: str | None = None):
        self.token = token or settings().telegram_bot_token
        self.base = f"https://api.telegram.org/bot{self.token}"

    def api(self, metodo: str, espera: float = 20, **datos) -> dict:
        """Llama un método de la Bot API. `espera` es el tiempo máximo de la petición HTTP."""
        datos = {k: v for k, v in datos.items() if v is not None}
        r = httpx.post(f"{self.base}/{metodo}", json=datos, timeout=espera)
        cuerpo = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400 or not cuerpo.get("ok", False):
            raise ErrorTelegram(r.status_code, cuerpo.get("description", r.text))
        return cuerpo.get("result")

    def _enviar(self, destino: str, texto: str, **extra) -> None:
        resumen = texto.replace("\n", " ")[:70]
        try:
            self.api("sendMessage", chat_id=chat_id(destino), text=a_html(texto), parse_mode="HTML", **extra)
        except ErrorTelegram as e:
            if e.codigo != 400:
                log.error("No se pudo enviar a %s: %s", destino, e)
                raise
            # Si el HTML generado no es válido, se manda como texto plano
            log.warning("Telegram rechazó el formato (%s); se envía sin formato", e)
            self.api("sendMessage", chat_id=chat_id(destino), text=texto, **extra)
        log.info("Respuesta a %s%s: %s", destino, " (con botones)" if extra.get("reply_markup") else "", resumen)

    def enviar_texto(self, destino: str, texto: str) -> None:
        for parte in partir(texto):
            self._enviar(destino, parte)

    def enviar_botones(self, destino: str, texto: str, botones: list[tuple[str, str]]) -> None:
        teclado = {"inline_keyboard": [[{"text": titulo, "callback_data": bid} for bid, titulo in botones]]}
        self._enviar(destino, texto, reply_markup=teclado)

    def enviar_plantilla(self, destino: str, texto: str) -> None:
        # Telegram no tiene plantillas ni ventana de 24 horas
        self.enviar_texto(destino, texto)

    def escribiendo(self, destino: str) -> None:
        try:
            self.api("sendChatAction", chat_id=chat_id(destino), action="typing")
        except Exception:
            pass

    def descargar_media(self, file_id: str) -> tuple[bytes, str]:
        info = self.api("getFile", file_id=file_id)
        r = httpx.get(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}", timeout=60)
        r.raise_for_status()
        ruta = info["file_path"].lower()
        mime = "application/pdf" if ruta.endswith(".pdf") else "image/png" if ruta.endswith(".png") else "image/jpeg"
        return r.content, mime

    def quitar_botones(self, chat: str, mensaje_id: int) -> None:
        try:
            self.api("editMessageReplyMarkup", chat_id=chat, message_id=mensaje_id, reply_markup={"inline_keyboard": []})
        except Exception:
            pass

    def responder_boton(self, callback_id: str) -> None:
        try:
            self.api("answerCallbackQuery", callback_query_id=callback_id)
        except Exception:
            pass


class ErrorTelegram(Exception):
    def __init__(self, codigo: int, descripcion: str):
        super().__init__(f"{codigo}: {descripcion}")
        self.codigo = codigo


COMANDOS = {"/start": "hola", "/ayuda": "¿Qué puedes hacer?", "/help": "¿Qué puedes hacer?",
            "/horario": "¿Qué tengo esta semana?", "/pendientes": "¿Qué tengo pendiente?"}


def interpretar_update(update: dict) -> dict | None:
    """Convierte una actualización de Telegram al formato común del bot:
    {id, destino, tipo, texto, media_id, mime, callback_id, mensaje_id}.
    Devuelve None si la actualización no interesa (ediciones, grupos, etc.)."""
    uid = f"tg:{update.get('update_id')}"
    if "callback_query" in update:
        cq = update["callback_query"]
        msg = cq.get("message") or {}
        chat = msg.get("chat", {})
        if chat.get("type", "private") != "private":
            return None
        return {"id": uid, "destino": f"{PREFIJO}{chat.get('id')}", "tipo": "boton", "texto": cq.get("data"),
                "media_id": None, "mime": None, "callback_id": cq.get("id"), "mensaje_id": msg.get("message_id")}

    msg = update.get("message")
    if not msg or msg.get("chat", {}).get("type") != "private":
        return None
    item = {"id": uid, "destino": f"{PREFIJO}{msg['chat']['id']}", "tipo": "otro", "texto": None,
            "media_id": None, "mime": None, "callback_id": None, "mensaje_id": msg.get("message_id")}
    if "text" in msg:
        texto = msg["text"].strip()
        comando = texto.split()[0].split("@")[0].lower() if texto.startswith("/") else None
        item.update(tipo="texto", texto=COMANDOS.get(comando, texto) if comando else texto)
    elif "photo" in msg:
        mayor = max(msg["photo"], key=lambda p: p.get("file_size", 0) or p.get("width", 0))
        item.update(tipo="imagen", media_id=mayor["file_id"], mime="image/jpeg", texto=msg.get("caption"))
    elif "document" in msg:
        doc = msg["document"]
        mime = doc.get("mime_type", "application/octet-stream")
        item.update(tipo="imagen" if mime.startswith("image/") else "documento",
                    media_id=doc["file_id"], mime=mime, texto=msg.get("caption"))
    return item
