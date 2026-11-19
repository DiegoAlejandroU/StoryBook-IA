"""Voz XTTS-v2 del perfil Avanzada (18 nov): proceso aparte, protocolo y respaldo con Piper."""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from storybook import config
from storybook.voice import tts, xtts

RAIZ = Path(__file__).resolve().parents[1]

# Un "XTTS" de mentira que habla el mismo protocolo (sin torch ni coqui-tts).
TRABAJADOR_FALSO = textwrap.dedent(
    """
    import json, sys, wave
    print(json.dumps({"listo": True, "segundos_carga": 0.1, "gpu": False, "sample_rate": 24000}))
    sys.stdout.flush()
    for linea in sys.stdin:
        pedido = json.loads(linea)
        if pedido["cmd"] == "salir":
            print(json.dumps({"ok": True})); sys.stdout.flush(); break
        if "error" in pedido["texto"]:
            print(json.dumps({"ok": False, "error": "RuntimeError: falló"})); sys.stdout.flush()
            continue
        print("aviso de una librería")  # líneas que no son JSON se ignoran
        with wave.open(pedido["salida"], "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(b"\\x10\\x00" * 2400)
        print(json.dumps({"ok": True, "segundos": 0.2, "duracion_s": 0.1, "gpu": False}))
        sys.stdout.flush()
    """
)


def _worker():
    especificacion = importlib.util.spec_from_file_location(
        "xtts_worker", RAIZ / "scripts" / "xtts_worker.py"
    )
    assert especificacion and especificacion.loader
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


def test_el_texto_se_parte_en_trozos_que_xtts_acepta() -> None:
    worker = _worker()
    texto = (
        "El dragón despertó. "
        + "La torre ardía con un fuego azul que nadie había visto jamás, " * 4
        + "y el niño corrió. ¿Quién lo ayudaría?"
    )
    trozos = worker.fragmentos(texto)
    assert all(len(t) <= worker.MAX_CARACTERES for t in trozos)
    assert " ".join(trozos).replace("  ", " ") == texto.strip()
    assert worker.fragmentos("Hola. Adiós.") == ["Hola. Adiós."]


@pytest.fixture
def falso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    script = tmp_path / "falso.py"
    script.write_text(TRABAJADOR_FALSO, encoding="utf-8")
    cfg = config.load_config("avanzada").voice

    def arrancar(_: Any) -> xtts.TrabajadorXTTS:
        return xtts.TrabajadorXTTS(
            [sys.executable, str(script)], 20, dict(__import__("os").environ)
        )

    monkeypatch.setattr(xtts, "trabajador", arrancar)
    return cfg


def test_narra_por_el_proceso_aparte(falso: Any) -> None:
    backend = xtts.XttsBackend(falso)
    backend.cargar()
    muestras, frecuencia = backend.sintetizar("Había una vez un faro.")
    assert frecuencia == 24000 and muestras.dtype == np.float32 and muestras.size == 2400
    info = backend.info()
    assert info["backend"] == "xtts" and info["voz"] == "Ana Florence"
    assert "CPML" in info["licencia"] and info["dispositivo"] == "cpu"
    with pytest.raises(xtts.XttsError, match="falló"):
        backend.sintetizar("un error")
    assert backend._trabajador is not None
    backend._trabajador.cerrar()
    assert not backend._trabajador.vivo


class _PiperFalso:
    nombre = "piper"

    def __init__(self) -> None:
        self.cargado = False

    def cargar(self) -> None:
        self.cargado = True

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        return np.full(2205, 0.1, dtype=np.float32), 22050

    def liberar(self) -> None:
        pass

    def info(self) -> dict[str, Any]:
        return {"backend": "piper", "voz": "es_MX-claude-high"}


def test_sin_el_entorno_de_xtts_narra_piper(tmp_path: Path) -> None:
    cfg = config.load_config("avanzada").voice.model_copy(update={"xtts_venv": "no-existe"})
    piper = _PiperFalso()
    narrador = tts.Narrador(cfg, xtts.XttsConRespaldo(cfg, piper))
    etapa = narrador.narrar([(1, "Una chica abre la puerta.")], tmp_path)
    assert piper.cargado and etapa.narraciones[0].sample_rate == 22050
    assert etapa.backend["backend"] == "piper" and etapa.backend["respaldo_de"] == "xtts"
    assert "Falta el entorno de XTTS" in etapa.backend["error_xtts"]


def test_el_perfil_avanzada_pide_xtts() -> None:
    cfg = config.load_config("avanzada").voice
    assert cfg.backend == "xtts"
    assert isinstance(tts.crear_backend(cfg), xtts.XttsConRespaldo)
    assert isinstance(tts.crear_backend(config.load_config("sdxl").voice), tts.PiperBackend)
    assert xtts.python_xtts(cfg).parent.parent == config.PROJECT_ROOT / ".venv-xtts"
