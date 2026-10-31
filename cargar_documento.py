"""Carga un documento institucional para que Lucho responda preguntas sobre la universidad (CU-15).

Uso:
  python cargar_documento.py "Calendario académico 2026-2" calendario.pdf
  python cargar_documento.py "Directorio de dependencias" directorio.txt

Si ya existía un documento con ese nombre, la versión anterior se desactiva.
"""
import re
import sys

from app import db

TAMANO_FRAGMENTO = 900  # caracteres aproximados por fragmento


def leer(ruta: str) -> str:
    if ruta.lower().endswith(".pdf"):
        from pypdf import PdfReader
        return "\n\n".join(p.extract_text() or "" for p in PdfReader(ruta).pages)
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def fragmentar(texto: str) -> list[str]:
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    fragmentos, actual = [], ""
    for p in parrafos:
        if actual and len(actual) + len(p) > TAMANO_FRAGMENTO:
            fragmentos.append(actual)
            actual = ""
        actual = f"{actual}\n\n{p}" if actual else p
    if actual:
        fragmentos.append(actual)
    return fragmentos


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    nombre, ruta = sys.argv[1], sys.argv[2]
    fragmentos = fragmentar(leer(ruta))
    if not fragmentos:
        print("❌ El documento no tiene texto extraíble (¿es un PDF escaneado?). Usa un PDF con texto o un .txt.")
        sys.exit(1)
    with db.conexion() as conn:
        conn.execute("UPDATE documentos_fragmentos SET activo = FALSE WHERE documento = %s", (nombre,))
        for f in fragmentos:
            conn.execute("INSERT INTO documentos_fragmentos (documento, contenido) VALUES (%s, %s)", (nombre, f))
    print(f"✅ '{nombre}' cargado en {len(fragmentos)} fragmentos.")


if __name__ == "__main__":
    main()
