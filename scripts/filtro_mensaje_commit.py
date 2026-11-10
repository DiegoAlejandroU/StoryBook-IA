"""Filtro de mensajes de commit para ``git filter-branch --msg-filter``.

Quita las líneas de coautoría o sesión de asistentes de IA (``Co-Authored-By: Claude …``,
``Claude-Session: …``) y las líneas en blanco que queden al final. Lee el mensaje por la
entrada estándar y lo escribe por la salida estándar. Lo usa ``scripts/quitar_coautor.ps1``.
"""

from __future__ import annotations

import re
import sys

PATRON: re.Pattern[str] = re.compile(
    r"^\s*(co-authored-by:\s*claude\b.*|claude-session:.*)$", re.IGNORECASE
)


def limpiar(mensaje: str) -> str:
    lineas = [linea for linea in mensaje.splitlines() if not PATRON.match(linea)]
    while lineas and not lineas[-1].strip():
        lineas.pop()
    return "\n".join(lineas) + "\n"


def main() -> int:
    datos = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape")
    sys.stdout.buffer.write(limpiar(datos).encode("utf-8", errors="surrogateescape"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
