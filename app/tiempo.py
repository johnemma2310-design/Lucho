"""Utilidades de fecha y hora en la zona horaria de Colombia (regla RN-08)."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .config import settings

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def zona() -> ZoneInfo:
    return ZoneInfo(settings().zona_horaria)


def ahora() -> datetime:
    return datetime.now(zona())


def a_local(dt: datetime) -> datetime:
    return dt.astimezone(zona())


def combinar(fecha: date, hora: time) -> datetime:
    return datetime.combine(fecha, hora, tzinfo=zona())


def nombre_dia(n: int) -> str:
    """n: 1 = lunes ... 7 = domingo."""
    return DIAS[n - 1]


def hora_texto(h: time) -> str:
    """08:00 -> '8:00 a. m.'"""
    sufijo = "a. m." if h.hour < 12 else "p. m."
    hora12 = h.hour % 12 or 12
    return f"{hora12}:{h.minute:02d} {sufijo}"


def fecha_texto(d: date | datetime) -> str:
    """'martes 20 de octubre'"""
    return f"{DIAS[d.isoweekday() - 1]} {d.day} de {MESES[d.month - 1]}"


def fecha_hora_texto(dt: datetime) -> str:
    dt = a_local(dt)
    return f"{fecha_texto(dt)}, {hora_texto(dt.time())}"
