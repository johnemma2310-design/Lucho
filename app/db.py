"""Conexión a PostgreSQL con un pool de conexiones."""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings().database_url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )
    return _pool


@contextmanager
def conexion():
    """Entrega una conexión dentro de una transacción: commit al salir, rollback si hay error."""
    with pool().connection() as conn:
        yield conn


def uno(sql: str, params=None):
    with conexion() as conn:
        return conn.execute(sql, params).fetchone()


def varios(sql: str, params=None):
    with conexion() as conn:
        return conn.execute(sql, params).fetchall()


def ejecutar(sql: str, params=None) -> int:
    with conexion() as conn:
        return conn.execute(sql, params).rowcount
