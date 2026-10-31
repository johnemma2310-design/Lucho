"""Envío del código de verificación al correo institucional (CU-01)."""
import logging
import smtplib
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("lucho.correo")


def enviar_codigo(destino: str, codigo: str) -> None:
    s = settings()
    if not s.smtp_host:
        # Modo desarrollo: el código aparece en el log del servidor
        log.warning("MODO DESARROLLO — código de verificación para %s: %s", destino, codigo)
        return
    msg = EmailMessage()
    msg["Subject"] = f"Tu código de Lucho: {codigo}"
    msg["From"] = s.smtp_remitente
    msg["To"] = destino
    msg.set_content(
        f"Hola,\n\nTu código para activar Lucho en WhatsApp es: {codigo}\n\n"
        "Vence en 10 minutos. Si no lo pediste, ignora este correo.\n\n"
        "Lucho — asistente académico de la Universidad Católica Luis Amigó"
    )
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if s.smtp_usuario:
            smtp.login(s.smtp_usuario, s.smtp_clave)
        smtp.send_message(msg)
