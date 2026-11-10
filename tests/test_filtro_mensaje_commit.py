"""Filtro que quita a Claude como coautor de los mensajes de commit (pedido de Diego)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

RAIZ = Path(__file__).resolve().parents[1]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "filtro", RAIZ / "scripts" / "filtro_mensaje_commit.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_quita_coautor_y_sesion() -> None:
    f = _modulo()
    mensaje = (
        "chore: evidencias de modelos (tarea 0.6)\n\n"
        "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
        "Claude-Session: https://claude.ai/code/session_x\n"
    )
    assert f.limpiar(mensaje) == "chore: evidencias de modelos (tarea 0.6)\n"


def test_no_toca_otros_coautores_ni_el_cuerpo() -> None:
    f = _modulo()
    mensaje = "feat: mezcla\n\nCuerpo con detalles.\n\nCo-Authored-By: Ana <ana@x.co>\n"
    assert f.limpiar(mensaje) == mensaje
    assert f.limpiar("fix: algo") == "fix: algo\n"


def test_insensible_a_mayusculas() -> None:
    f = _modulo()
    assert f.limpiar("x\n\nco-authored-by: claude <a@b.c>\n") == "x\n"
