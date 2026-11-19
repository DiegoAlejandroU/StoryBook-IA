"""Voz XTTS-v2 (perfil Avanzada, 18 nov) a través de su proceso aparte.

XTTS-v2 necesita ``torchaudio``, que no existe para el torch de la app, así que corre en
``.venv-xtts`` (``scripts/xtts_worker.py``) y aquí se le habla por stdin/stdout con una
línea JSON por escena. El proceso se arranca una sola vez y queda vivo entre escenas y
entre historias (cargar XTTS tarda ~15 s); el modelo vive en su RAM y sube a la GPU solo
mientras narra.

``XttsConRespaldo`` es lo que usa el narrador: si XTTS no arranca (falta el entorno o el
modelo), narra con Piper y lo deja anotado en el manifest. Así una historia nunca queda sin
voz por el perfil Avanzada.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import IO, Any, Final

import numpy as np
import soundfile as sf

from storybook import config
from storybook.config import VoiceConfig
from storybook.logging_utils import get_logger, kv

logger = get_logger(__name__)

WORKER: Final = config.PROJECT_ROOT / "scripts" / "xtts_worker.py"
LICENCIA: Final = "CPML (Coqui Public Model License, uso no comercial)"
COMANDO_ENTORNO: Final = (
    "powershell -ExecutionPolicy Bypass -File .\\scripts\\setup_windows.ps1 -Paso avanzada"
)


class XttsError(Exception):
    """El proceso de XTTS no arrancó o no respondió."""


def python_xtts(cfg: VoiceConfig) -> Path:
    carpeta = config.PROJECT_ROOT / cfg.xtts_venv
    return carpeta / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class TrabajadorXTTS:
    """El proceso ``xtts_worker.py``: arranque, pedidos con tiempo límite y cierre."""

    def __init__(self, comando: list[str], timeout_s: float, entorno: dict[str, str]) -> None:
        self.comando = comando
        self.timeout_s = timeout_s
        self._respuestas: queue.Queue[str | None] = queue.Queue()
        self._log = tempfile.NamedTemporaryFile(  # noqa: SIM115 (vive con el proceso)
            prefix="storybook_xtts_", suffix=".log", delete=False
        )
        self._proceso = subprocess.Popen(
            comando,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            text=True,
            encoding="utf-8",
            env=entorno,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert self._proceso.stdout is not None
        threading.Thread(target=self._leer, args=(self._proceso.stdout,), daemon=True).start()
        self.arranque = self._esperar(timeout_s)
        if not self.arranque.get("listo"):
            error = self.arranque.get("error", "sin detalle")
            self.cerrar()
            raise XttsError(f"XTTS no cargó: {error} (registro: {self._log.name})")

    def _leer(self, salida: IO[str]) -> None:
        for linea in salida:
            self._respuestas.put(linea)
        self._respuestas.put(None)  # el proceso terminó

    def _esperar(self, timeout_s: float) -> dict[str, Any]:
        limite = time.monotonic() + timeout_s
        while True:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise XttsError(f"XTTS no respondió en {timeout_s:.0f} s ({self._log.name})")
            try:
                linea = self._respuestas.get(timeout=restante)
            except queue.Empty as exc:
                raise XttsError(f"XTTS no respondió en {timeout_s:.0f} s") from exc
            if linea is None:
                raise XttsError(f"El proceso de XTTS terminó (registro: {self._log.name})")
            linea = linea.strip()
            if linea.startswith("{"):
                return json.loads(linea)  # otras líneas (avisos de librerías) se ignoran

    @property
    def vivo(self) -> bool:
        return self._proceso.poll() is None

    def pedir(self, pedido: dict[str, Any]) -> dict[str, Any]:
        if not self.vivo or self._proceso.stdin is None:
            raise XttsError("El proceso de XTTS no está corriendo")
        self._proceso.stdin.write(json.dumps(pedido, ensure_ascii=False) + "\n")
        self._proceso.stdin.flush()
        respuesta = self._esperar(self.timeout_s)
        if not respuesta.get("ok"):
            raise XttsError(respuesta.get("error", "XTTS falló sin detalle"))
        return respuesta

    def cerrar(self) -> None:
        if self.vivo and self._proceso.stdin is not None:
            try:
                self._proceso.stdin.write('{"cmd": "salir"}\n')
                self._proceso.stdin.flush()
                self._proceso.wait(timeout=10)
            except Exception:
                self._proceso.kill()
        self._log.close()


_TRABAJADOR: TrabajadorXTTS | None = None
_CANDADO = threading.Lock()


def trabajador(cfg: VoiceConfig) -> TrabajadorXTTS:
    """El proceso de XTTS de esta app (se arranca la primera vez)."""
    from storybook.hub import local_snapshot

    global _TRABAJADOR
    with _CANDADO:
        if _TRABAJADOR is not None and _TRABAJADOR.vivo:
            return _TRABAJADOR
        python = python_xtts(cfg)
        if not python.is_file():
            raise XttsError(f"Falta el entorno de XTTS ({python.parent.parent}). {COMANDO_ENTORNO}")
        modelo = local_snapshot(cfg.xtts_repo_id)
        comando = [str(python), "-I", str(WORKER), "--modelo", str(modelo)]
        if not cfg.xtts_gpu:
            comando.append("--cpu")
        entorno = {
            **os.environ,
            "COQUI_TOS_AGREED": "1",  # CPML aceptada por Diego (18 nov)
            "HF_HUB_OFFLINE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        _TRABAJADOR = TrabajadorXTTS(comando, cfg.xtts_timeout_s, entorno)
        logger.info("xtts_listo", extra=kv(**_TRABAJADOR.arranque))
        return _TRABAJADOR


@atexit.register
def cerrar_trabajador() -> None:
    global _TRABAJADOR
    if _TRABAJADOR is not None:
        _TRABAJADOR.cerrar()
        _TRABAJADOR = None


class XttsBackend:
    """``TTSBackend`` con el proceso de XTTS (24 kHz, voz incluida en el modelo)."""

    nombre = "xtts"

    def __init__(self, cfg: VoiceConfig) -> None:
        self.cfg = cfg
        self._trabajador: TrabajadorXTTS | None = None
        self._ultima: dict[str, Any] = {}

    def cargar(self) -> None:
        self._trabajador = trabajador(self.cfg)

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        if self._trabajador is None:
            raise XttsError("XTTS no está cargado")
        with tempfile.TemporaryDirectory(prefix="storybook_voz_") as carpeta:
            salida = Path(carpeta) / "voz.wav"
            self._ultima = self._trabajador.pedir(
                {
                    "cmd": "narrar",
                    "texto": texto,
                    "salida": str(salida),
                    "speaker": self.cfg.xtts_speaker,
                    "idioma": self.cfg.xtts_idioma,
                }
            )
            muestras, frecuencia = sf.read(str(salida), dtype="float32")
        return np.asarray(muestras, dtype=np.float32), int(frecuencia)

    def liberar(self) -> None:
        """El proceso sigue vivo para la siguiente escena (el modelo ya está en su RAM)."""

    def info(self) -> dict[str, Any]:
        arranque = self._trabajador.arranque if self._trabajador else {}
        return {
            "backend": self.nombre,
            "repo": self.cfg.xtts_repo_id,
            "voz": self.cfg.xtts_speaker,
            "idioma": self.cfg.xtts_idioma,
            "licencia": LICENCIA,
            "dispositivo": "cuda" if self._ultima.get("gpu", arranque.get("gpu")) else "cpu",
            "segundos_carga": arranque.get("segundos_carga"),
            "proceso": self.cfg.xtts_venv,
        }


class XttsConRespaldo:
    """XTTS si arranca; si no, Piper (y el motivo queda en ``info``)."""

    nombre = "xtts"

    def __init__(self, cfg: VoiceConfig, respaldo: Any) -> None:
        self.xtts = XttsBackend(cfg)
        self.respaldo = respaldo
        self._activo: Any = self.xtts
        self._error: str | None = None

    def cargar(self) -> None:
        try:
            self.xtts.cargar()
            self._activo = self.xtts
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            logger.warning("xtts_no_disponible", extra=kv(error=self._error, respaldo="piper"))
            self._activo = self.respaldo
            self.respaldo.cargar()

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        return self._activo.sintetizar(texto)

    def liberar(self) -> None:
        self._activo.liberar()

    def info(self) -> dict[str, Any]:
        datos = dict(self._activo.info())
        if self._error is not None:
            datos.update(respaldo_de="xtts", error_xtts=self._error)
        return datos
