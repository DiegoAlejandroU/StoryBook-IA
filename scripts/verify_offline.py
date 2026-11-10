"""Verificación offline (tarea 5.3): el pipeline no intenta conexiones fuera de este equipo.

Mientras corre el pipeline, bloquea y registra toda conexión de red que no vaya a
``localhost`` (Ollama escucha en localhost:11434). Si hubo algún intento, termina con
código 1 y lo informa. Úsalo además con el Wi-Fi apagado (tarea 5.4).

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/verify_offline.py                 # pipeline simulado (sin GPU)
    uv run python scripts/verify_offline.py --real          # modelos reales (Ollama abierto)
    uv run python scripts/verify_offline.py --real --n 3 --samples   # 3 historias -> samples/
"""

from __future__ import annotations

import argparse
import shutil
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.logging_utils import get_logger, kv, setup_logging

log = get_logger("verify_offline")

HOSTS_LOCALES: Final = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})
IDEAS: Final = (
    ("Un faro abandonado que se enciende solo cada noche", "misterio"),
    ("El último dragón vive escondido en una biblioteca", "fantasia"),
    ("Un perro y un gato deben cruzar la ciudad para volver a casa", "infantil"),
)


class ConexionBloqueada(ConnectionError):
    """Intento de conexión fuera de este equipo."""


def es_local(host: Any) -> bool:
    texto = str(host).strip("[]").lower()
    return texto in HOSTS_LOCALES or texto.startswith("127.") or texto.endswith(".localhost")


def _host(direccion: Any) -> Any:
    return direccion[0] if isinstance(direccion, tuple) and direccion else direccion


@contextmanager
def vigilar_red() -> Iterator[list[str]]:
    """Bloquea y registra conexiones y resoluciones DNS que no sean locales."""
    intentos: list[str] = []
    originales = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)
    conectar, conectar_ex, resolver = originales

    def registrar(tipo: str, destino: Any) -> None:
        intentos.append(f"{tipo} {destino}")
        log.error("conexion_externa_bloqueada", extra=kv(tipo=tipo, destino=str(destino)))
        raise ConexionBloqueada(f"Conexión externa bloqueada: {destino}")

    def connect(self: socket.socket, direccion: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6) and not es_local(_host(direccion)):
            registrar("connect", direccion)
        return conectar(self, direccion)

    def connect_ex(self: socket.socket, direccion: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6) and not es_local(_host(direccion)):
            registrar("connect_ex", direccion)
        return conectar_ex(self, direccion)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host is not None and not es_local(host):
            registrar("dns", host)
        return resolver(host, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    try:
        yield intentos
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = originales  # type: ignore[method-assign,assignment]


def generar_historias(
    real: bool, n: int, perfil: str, raiz: Path | None = None
) -> tuple[list[Any], list[str]]:
    from storybook.pipeline import Pipeline

    dependencias = None
    if not real:
        from storybook.mock import dependencias_simuladas

        dependencias = dependencias_simuladas()
    pipeline = Pipeline(config.load_config(perfil), dependencias, raiz)
    historias: list[Any] = []
    errores: list[str] = []
    for idea, genero in IDEAS[:n]:
        try:
            historias.append(pipeline.generar(idea, genero))
        except Exception as exc:  # se informa y se sigue con la siguiente idea
            errores.append(f"{idea[:40]}…: {type(exc).__name__}: {exc}")
            log.exception("historia_fallida", extra=kv(idea=idea))
    return historias, errores


def copiar_a_samples(carpeta: Path, destino: Path | None = None) -> Path:
    destino = (destino or config.SAMPLES_DIR) / carpeta.name
    shutil.copytree(carpeta, destino, dirs_exist_ok=True)
    return destino


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--real", action="store_true", help="modelos reales (Ollama abierto)")
    parser.add_argument("--n", type=int, default=1, choices=range(1, len(IDEAS) + 1))
    parser.add_argument("--perfil", default="rapido")
    parser.add_argument("--samples", action="store_true", help="copiar las historias a samples/")
    args = parser.parse_args(argv)
    setup_logging()

    with vigilar_red() as intentos:
        historias, errores = generar_historias(args.real, args.n, args.perfil)

    modo = "real" if args.real else "simulado"
    sys.stdout.write(f"\nVerificación offline ({modo}, perfil {args.perfil}):\n")
    for historia in historias:
        completa = "completa" if historia.completa else "INCOMPLETA"
        sys.stdout.write(
            f"- {historia.titulo} ({historia.run_id}): {completa}, "
            f"{historia.manifest.get('segundos', {}).get('total', '-')} s\n"
        )
        if args.samples:
            sys.stdout.write(f"  copiada a {copiar_a_samples(historia.carpeta)}\n")
    for error in errores:
        sys.stdout.write(f"- ERROR: {error}\n")
    if intentos:
        sys.stdout.write(f"\nFALLO: {len(intentos)} intentos de conexión externa:\n")
        sys.stdout.writelines(f"  {i}\n" for i in intentos)
        return 1
    sys.stdout.write("\nOK: ninguna conexión fuera de este equipo.\n")
    return 0 if historias and not errores else 2


if __name__ == "__main__":
    sys.exit(main())
