"""CU-09 a CU-12: recordatorios, avisos y resúmenes."""

from app import bot, db, horario, ia, programador, recordatorios
from tests.conftest import CLASES_EJEMPLO, momento


def test_calculo_de_avisos():
    evento = momento("2026-10-20 08:00")
    avisos = recordatorios.calcular_avisos(evento, True, [7], momento("2026-10-07 10:00"))
    assert avisos == [momento("2026-10-13 19:00"), momento("2026-10-19 19:00"), momento("2026-10-20 06:00")]
    # Sin hora: día anterior 7 p. m. y el mismo día 7 a. m.
    sin_hora = recordatorios.calcular_avisos(momento("2026-10-09 23:59"), False, None, momento("2026-10-07 10:00"))
    assert sin_hora == [momento("2026-10-08 19:00"), momento("2026-10-09 07:00")]
    # Avisos ya pasados se omiten
    assert recordatorios.calcular_avisos(evento, True, None, momento("2026-10-19 20:00")) == [momento("2026-10-20 06:00")]


def test_crear_y_errores(estudiante_activo):
    eid = estudiante_activo["id"]
    hoy = momento("2026-10-07 10:00")
    r = recordatorios.crear(eid, "Parcial de Estructuras", "2026-10-20", "08:00", "parcial", "Estructuras", momento=hoy)
    assert r["fecha"] == "martes 20 de octubre, 8:00 a. m." and len(r["avisos"]) == 2
    assert "ya pasó" in recordatorios.crear(eid, "X", "2026-10-01", momento=hoy)["error"]
    assert "error" in recordatorios.crear(eid, "X", "20/10/2026", momento=hoy)


def test_listar_actualizar_completar_eliminar(estudiante_activo):
    eid = estudiante_activo["id"]
    hoy = momento("2026-10-07 10:00")
    a = recordatorios.crear(eid, "Taller de redes", "2099-10-09", None, "entrega", momento=hoy)
    b = recordatorios.crear(eid, "Parcial", "2099-10-20", "08:00", "parcial", momento=hoy)
    assert [x["titulo"] for x in recordatorios.listar(eid)] == ["Taller de redes", "Parcial"]
    nuevo = recordatorios.actualizar(eid, b["id"], fecha="2099-10-22", momento=hoy)
    assert "22 de octubre" in nuevo["fecha"] and "8:00" in nuevo["fecha"]
    recordatorios.completar(eid, a["id"])
    assert [x["titulo"] for x in recordatorios.listar(eid)] == ["Parcial"]
    assert recordatorios.eliminar(eid, nuevo["id"])["eliminado"]
    assert recordatorios.listar(eid) == []


def test_programador_envia_avisos_una_vez(canal, estudiante_activo):
    eid = estudiante_activo["id"]
    recordatorios.crear(eid, "Parcial de Cálculo", "2026-10-20", "08:00", "parcial", "Cálculo",
                        momento=momento("2026-10-07 10:00"))
    assert programador.revisar(momento("2026-10-19 18:59"))["recordatorios"] == 0
    assert programador.revisar(momento("2026-10-19 19:00"))["recordatorios"] == 1
    assert "mañana a las 8:00 a. m." in canal.ultimo()[2]
    assert programador.revisar(momento("2026-10-19 19:05"))["recordatorios"] == 0
    assert programador.revisar(momento("2026-10-20 06:00"))["recordatorios"] == 1
    assert any("Es hoy a las 8:00" in e[2] for e in canal.enviados[-2:])


def test_ventana_24_horas_usa_plantilla(canal, estudiante_activo):
    eid = estudiante_activo["id"]
    recordatorios.crear(eid, "Entrega", "2026-10-20", None, "entrega", momento=momento("2026-10-07 10:00"))
    db.ejecutar("UPDATE estudiantes SET ultimo_mensaje_at = %s WHERE id = %s", (momento("2026-10-15 10:00"), eid))
    programador.revisar(momento("2026-10-19 19:00"))
    assert canal.ultimo()[0] == "plantilla"


def test_falla_de_envio_reintenta(canal, estudiante_activo, monkeypatch):
    eid = estudiante_activo["id"]
    recordatorios.crear(eid, "Quiz", "2026-10-20", "10:00", "quiz", momento=momento("2026-10-07 10:00"))

    def falla(*a):
        raise RuntimeError("WhatsApp caído")
    monkeypatch.setattr(canal, "enviar_texto", falla)
    monkeypatch.setattr(canal, "enviar_plantilla", falla)
    assert programador.revisar(momento("2026-10-19 19:00"))["recordatorios"] == 0
    aviso = db.uno("SELECT * FROM avisos ORDER BY enviar_at LIMIT 1")
    assert aviso["intentos"] == 1 and not aviso["enviado"]
    monkeypatch.undo()
    from app.canales import usar_canal
    usar_canal(canal)
    assert programador.revisar(momento("2026-10-19 19:02"))["recordatorios"] == 1


def test_aviso_antes_de_clase_y_resumen(canal, estudiante_activo):
    eid = estudiante_activo["id"]
    clases, _ = horario.validar_clases(CLASES_EJEMPLO)
    horario.confirmar_horario(eid, clases, reemplazar=True)
    db.ejecutar("UPDATE estudiantes SET aviso_clase = TRUE, minutos_aviso_clase = 15 WHERE id = %s", (eid,))
    recordatorios.crear(eid, "Taller", "2026-10-07", None, "entrega", momento=momento("2026-10-04 10:00"))

    r = programador.revisar(momento("2026-10-05 06:00"))  # lunes
    assert r["resumen_diario"] == 1
    assert "Cálculo Diferencial" in canal.ultimo()[2] and "Taller" in canal.ultimo()[2]
    assert programador.revisar(momento("2026-10-05 06:01"))["resumen_diario"] == 0

    assert programador.revisar(momento("2026-10-05 07:44"))["clases"] == 0
    assert programador.revisar(momento("2026-10-05 07:45"))["clases"] == 1
    assert "En 15 minutos tienes *Cálculo Diferencial*" in canal.ultimo()[2]
    assert programador.revisar(momento("2026-10-05 07:50"))["clases"] == 0

    # Festivo: no hay resumen ni avisos
    assert programador.revisar(momento("2026-10-12 07:45")) == {
        "recordatorios": 0, "clases": 0, "resumen_diario": 0, "resumen_semanal": 0}


def test_resumen_semanal(canal, estudiante_activo):
    eid = estudiante_activo["id"]
    clases, _ = horario.validar_clases(CLASES_EJEMPLO)
    horario.confirmar_horario(eid, clases, reemplazar=True)
    db.ejecutar("UPDATE estudiantes SET resumen_semanal = TRUE, resumen_diario = FALSE WHERE id = %s", (eid,))
    assert programador.revisar(momento("2026-10-04 17:59"))["resumen_semanal"] == 0
    assert programador.revisar(momento("2026-10-04 18:00"))["resumen_semanal"] == 1
    assert "lunes 5 de octubre" in canal.ultimo()[2]


def test_fechas_de_parciales_desde_foto(canal, estudiante_activo, monkeypatch):
    """CU-09 flujo 1a: foto del programa del curso con fechas de parciales."""
    monkeypatch.setattr(ia, "extraer", lambda **kw: {
        "tipo_documento": "evaluaciones", "confianza": "alta", "clases": [],
        "evaluaciones": [
            {"tipo": "parcial", "titulo": "Primer parcial", "materia": "Física", "fecha": "2026-09-15"},
            {"tipo": "parcial", "titulo": "Segundo parcial", "materia": "Física", "fecha": "2026-10-27", "hora": "10:00"},
            {"tipo": "entrega", "titulo": "Proyecto final", "materia": "Física", "fecha": "2026-11-24"},
        ]})
    tel = estudiante_activo["telefono"]
    hoy = momento("2026-10-07 10:00")
    bot.procesar_mensaje(tel, "imagen", None, b"x", "image/jpeg", momento=hoy)
    assert "Primer parcial" not in canal.enviados[-2][2]  # ya pasó
    assert "Segundo parcial" in canal.enviados[-2][2]
    bot.procesar_mensaje(tel, "boton", "btn_guardar", momento=hoy)
    assert "Guardé 2 recordatorio" in canal.ultimo()[2]
    assert len(recordatorios.listar(estudiante_activo["id"], momento=hoy)) == 2


def test_conversacion_guarda_historial(canal, estudiante_activo, monkeypatch):
    def conversar_falso(sistema, historial, mensaje, declaraciones, ejecutar):
        assert "Lucho" in sistema and "Ana" in sistema
        return f"Respuesta a: {mensaje}"
    monkeypatch.setattr(ia, "conversar", conversar_falso)
    bot.procesar_mensaje(estudiante_activo["telefono"], "texto", "hola Lucho")
    assert canal.ultimo()[2] == "Respuesta a: hola Lucho"
    assert db.uno("SELECT count(*) AS n FROM mensajes")["n"] == 2
