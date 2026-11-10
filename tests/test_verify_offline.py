"""Verificación offline (tarea 5.3): bloqueo de red y pipeline simulado sin conexiones."""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path
from types import ModuleType

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("vo", RAIZ / "scripts" / "verify_offline.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_bloquea_lo_externo_y_deja_lo_local() -> None:
    vo = _modulo()
    servidor = socket.socket()
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    puerto = servidor.getsockname()[1]
    original = socket.socket.connect
    try:
        with vo.vigilar_red() as intentos:
            with socket.create_connection(("127.0.0.1", puerto), timeout=2):
                pass  # localhost (como Ollama) está permitido
            with pytest.raises(vo.ConexionBloqueada):
                socket.getaddrinfo("huggingface.co", 443)
            cliente = socket.socket()
            with pytest.raises(vo.ConexionBloqueada):
                cliente.connect(("93.184.216.34", 80))
            cliente.close()
        assert intentos == ["dns huggingface.co", "connect ('93.184.216.34', 80)"]
    finally:
        servidor.close()
    assert socket.socket.connect is original  # se restaura al salir


def test_es_local() -> None:
    vo = _modulo()
    assert vo.es_local("localhost") and vo.es_local("127.0.0.1") and vo.es_local("[::1]")
    assert not vo.es_local("huggingface.co") and not vo.es_local("10.0.0.5")


def test_pipeline_simulado_sin_conexiones(tmp_path: Path) -> None:
    vo = _modulo()
    with vo.vigilar_red() as intentos:
        historias, errores = vo.generar_historias(False, 1, "rapido", raiz=tmp_path)
    assert intentos == [] and errores == []
    (historia,) = historias
    assert historia.completa
    destino = vo.copiar_a_samples(historia.carpeta, tmp_path / "samples")
    assert (destino / "story.json").is_file() and (destino / "mix_5.wav").is_file()
