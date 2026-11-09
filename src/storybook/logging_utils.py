"""Logging estructurado de StoryBook (consola legible + archivo JSON Lines).

Uso:
    from storybook.logging_utils import get_logger, kv, setup_logging

    setup_logging(log_file=run_dir / "run.log")
    log = get_logger(__name__)
    log.info("etapa_terminada", extra=kv(etapa="imagen", segundos=12.4))

Los campos pasados con ``kv`` aparecen como ``clave=valor`` en consola y como claves del
objeto JSON en el archivo, lo que permite analizar los logs de cada ejecución.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CTX_KEY = "ctx"
_LIBRERIAS_RUIDOSAS = (
    "httpx",
    "httpcore",
    "urllib3",
    "huggingface_hub",
    "filelock",
    "PIL",
    "matplotlib",
    "diffusers",
    "transformers",
    "faster_whisper",
    "numba",
)


def kv(**campos: Any) -> dict[str, dict[str, Any]]:
    """Empaqueta campos estructurados para el parámetro ``extra`` de logging."""
    return {CTX_KEY: campos}


def _formatear_valor(valor: Any) -> str:
    if isinstance(valor, float):
        return f"{valor:.3f}".rstrip("0").rstrip(".")
    texto = str(valor)
    return f'"{texto}"' if " " in texto else texto


class ConsoleFormatter(logging.Formatter):
    """``HH:MM:SS NIVEL logger | mensaje  clave=valor ...``"""

    def format(self, record: logging.LogRecord) -> str:
        hora = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        base = f"{hora} {record.levelname:<7} {record.name} | {record.getMessage()}"
        ctx = getattr(record, CTX_KEY, None)
        if isinstance(ctx, dict) and ctx:
            base += "  " + " ".join(f"{k}={_formatear_valor(v)}" for k, v in ctx.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class JsonLinesFormatter(logging.Formatter):
    """Una línea JSON por evento; serializa a texto lo que no sea JSON nativo."""

    def format(self, record: logging.LogRecord) -> str:
        evento: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
        }
        ctx = getattr(record, CTX_KEY, None)
        if isinstance(ctx, dict):
            evento.update(ctx)
        if record.exc_info:
            evento["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


def setup_logging(level: str | None = None, log_file: Path | None = None) -> None:
    """Configura el logger raíz. Es idempotente: reemplaza handlers previos."""
    nivel = (level or os.environ.get("STORYBOOK_LOG_LEVEL") or "INFO").upper()
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)

    # En Windows, si la salida se redirige a un archivo, la consola puede usar cp1252.
    reconfigure = getattr(sys.stderr, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="backslashreplace")

    consola = logging.StreamHandler(sys.stderr)
    consola.setFormatter(ConsoleFormatter())
    raiz.addHandler(consola)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        archivo = logging.FileHandler(log_file, encoding="utf-8")
        archivo.setFormatter(JsonLinesFormatter())
        raiz.addHandler(archivo)

    for nombre in _LIBRERIAS_RUIDOSAS:
        logging.getLogger(nombre).setLevel(max(logging.WARNING, raiz.level))


def get_logger(nombre: str) -> logging.Logger:
    return logging.getLogger(nombre)
