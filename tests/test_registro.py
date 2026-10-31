"""CU-01: registro y verificación con correo institucional."""
from app import bot, correo, db
from tests.conftest import momento

TEL = "573005556677"


def _enviar(texto, cuando="2026-10-07 10:00", tipo="texto"):
    bot.procesar_mensaje(TEL, tipo, texto, momento=momento(cuando))


def _estado():
    return db.uno("SELECT * FROM estudiantes WHERE telefono = %s", (TEL,))


def test_registro_completo(canal, monkeypatch):
    codigos = []
    monkeypatch.setattr(correo, "enviar_codigo", lambda destino, codigo: codigos.append((destino, codigo)))

    _enviar("hola")
    assert "Lucho" in canal.textos()
    assert canal.ultimo()[3] == ["btn_acepto", "btn_no_acepto"]

    _enviar("btn_acepto", tipo="boton")
    assert _estado()["estado_registro"] == "esperando_correo"
    assert _estado()["acepto_datos_at"] is not None

    _enviar("ana@gmail.com")
    assert "institucionales" in canal.ultimo()[2]

    _enviar("Ana.Gomez@amigo.edu.co")
    assert codigos == [("ana.gomez@amigo.edu.co", codigos[0][1])]
    assert _estado()["estado_registro"] == "esperando_codigo"

    _enviar("000000" if codigos[0][1] != "000000" else "111111")
    assert "Te quedan 2" in canal.ultimo()[2]

    _enviar(f"mi código es {codigos[0][1]}")
    assert _estado()["correo"] == "ana.gomez@amigo.edu.co"

    _enviar("ana maría gómez")
    assert _estado()["nombre"] == "Ana María Gómez"
    _enviar("Ingeniería de Sistemas")
    e = _estado()
    assert e["estado_registro"] == "activo" and e["programa"] == "Ingeniería de Sistemas"
    assert "PDF" in canal.ultimo()[2]


def test_no_acepta_politica(canal):
    _enviar("hola")
    _enviar("btn_no_acepto", tipo="boton")
    assert _estado()["estado_registro"] == "esperando_aceptacion"
    assert "autorización" in canal.ultimo()[2]


def test_codigo_vencido_y_bloqueo(canal, monkeypatch):
    codigos = []
    monkeypatch.setattr(correo, "enviar_codigo", lambda d, c: codigos.append(c))
    _enviar("hola")
    _enviar("acepto")
    _enviar("x@amigo.edu.co", "2026-10-07 10:00")
    _enviar(codigos[0], "2026-10-07 10:11")  # 11 minutos después
    assert "venció" in canal.ultimo()[2]

    _enviar("reenviar", "2026-10-07 10:12")
    malo = "123456" if codigos[1] != "123456" else "654321"
    for _ in range(3):
        _enviar(malo, "2026-10-07 10:13")
    assert _estado()["bloqueado_hasta"] is not None
    _enviar("x@amigo.edu.co", "2026-10-07 10:20")
    assert "espera" in canal.ultimo()[2]


def test_traslado_de_cuenta_a_otro_numero(canal, monkeypatch, estudiante_activo):
    codigos = []
    monkeypatch.setattr(correo, "enviar_codigo", lambda d, c: codigos.append(c))
    db.ejecutar("INSERT INTO clases (estudiante_id, materia, dia_semana, hora_inicio, hora_fin) VALUES (%s,'X',1,'08:00','10:00')",
                (estudiante_activo["id"],))
    _enviar("hola")
    _enviar("acepto")
    _enviar("ana.gomez@amigo.edu.co")
    _enviar(codigos[0])
    e = _estado()
    assert e["id"] == estudiante_activo["id"] and e["estado_registro"] == "activo"
    assert db.uno("SELECT count(*) AS n FROM clases WHERE estudiante_id = %s", (e["id"],))["n"] == 1
    assert "pasé a este número" in canal.ultimo()[2]
