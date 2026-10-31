"""Configuración de Lucho, leída de variables de entorno o del archivo .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Canal de mensajería: "telegram" (MVP) o "whatsapp"
    canal: str = "telegram"
    telegram_bot_token: str = ""

    # Base de datos (cadena de conexión de Neon)
    database_url: str

    # WhatsApp Cloud API (Meta for Developers)
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "lucho-verificacion"
    whatsapp_app_secret: str = ""  # para validar la firma del webhook; vacío = no se valida (solo desarrollo)
    whatsapp_api_version: str = "v23.0"
    # Plantillas aprobadas en Meta para mensajes fuera de la ventana de 24 horas.
    # Cada una debe tener un solo parámetro {{1}} en el cuerpo.
    plantilla_aviso: str = "lucho_aviso"
    plantilla_idioma: str = "es"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.7-flash"
    gemini_model_respaldo: str = "gemini-3.5-flash"  # se usa si el principal está saturado

    # Registro
    dominio_correo: str = "amigo.edu.co"
    secreto_otp: str = "cambia-este-secreto"
    url_politica_datos: str = "https://www.ucatolicaluisamigo.edu.co"

    # Correo para enviar el código de verificación. Si smtp_host está vacío,
    # el código solo se escribe en el log del servidor (modo desarrollo).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_usuario: str = ""
    smtp_clave: str = ""
    smtp_remitente: str = "Lucho <no-responder@amigo.edu.co>"

    zona_horaria: str = "America/Bogota"
    activar_programador: bool = True


@lru_cache
def settings() -> Settings:
    return Settings()
