"""Tarea 6.2 (complemento): qué evita que AudioLDM dé ambientes casi mudos.

En la batería 6.2, AudioLDM solo pasó el control de calidad en 12 de 20 escenas. Las demás
fueron clips de −47 a −75 dBFS o casi en silencio, aun sin adjetivos como "soft". Este
script toma los 20 ``prompt_sonido`` de la última batería y los genera con 4 variantes,
con las mismas 2 seeds para todas:

- ``base``: como en producción (guidance 2.5).
- ``sufijo``: termina el prompt en ", high quality, clear". La documentación de AudioLDM
  recomienda adjetivos de calidad.
- ``guia_alta``: guidance 4.0, es decir, más apego al prompt.
- ``sufijo_guia``: las dos cosas.

Mide el nivel (dBFS), la fracción en silencio y si el clip pasa el control de producción
(``problema_de_ambiente``). Una escena "pasa" si alguna de las 2 seeds sirve, como en
producción, donde hay 2 intentos. Los clips quedan en
``experiments/runs/<id>/audioldm_prompts/`` para escucharlos.

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/f6_audioldm_prompts.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.schemas import Escena
from storybook.sound.generator import (
    a_mono,
    fraccion_en_silencio,
    nivel_dbfs,
    preparar_prompt_audio,
    problema_de_ambiente,
)
from storybook.storage import cargar_bible

log = get_logger("f6_audioldm_prompts")

SUFIJO: Final = ", high quality, clear"
GUIA_ALTA: Final = 4.0
VARIANTES: Final[dict[str, tuple[str, float | None]]] = {
    "base": ("", None),
    "sufijo": (SUFIJO, None),
    "guia_alta": ("", GUIA_ALTA),
    "sufijo_guia": (SUFIJO, GUIA_ALTA),
}
SEEDS: Final = (101, 1101)
RUNS: Final = config.PROJECT_ROOT / "experiments" / "runs"
EVIDENCIAS: Final = config.DOCS_DIR / "evidencias"


def ultima_bateria(raiz: Path = RUNS) -> Path:
    baterias = sorted(d for d in raiz.iterdir() if (d / "c3_ipadapter").is_dir())
    if not baterias:
        raise FileNotFoundError(f"No hay baterías con c3_ipadapter en {raiz}")
    return baterias[-1]


def recolectar_escenas(bateria: Path) -> list[tuple[str, Escena]]:
    """(historia, escena) de cada historia completa de la batería."""
    escenas = []
    for story in sorted((bateria / "c3_ipadapter").glob("*/story.json")):
        bible = cargar_bible(story.parent)
        escenas += [(story.parent.name, e) for e in bible.escenas]
    return escenas


def con_sufijo(escena: Escena, sufijo: str) -> Escena:
    if not sufijo:
        return escena
    prompt = escena.prompt_sonido.rstrip(" .;,") + sufijo
    return escena.model_copy(update={"prompt_sonido": prompt})


def ablacion(
    backend: Any,
    escenas: Sequence[tuple[str, Escena]],
    duracion_s: float,
    variantes: Mapping[str, tuple[str, float | None]] = VARIANTES,
    seeds: Sequence[int] = SEEDS,
    carpeta: Path | None = None,
) -> list[dict[str, Any]]:
    """Genera cada escena con cada variante y seed. ``backend`` es un backend de sonido."""
    import soundfile as sf

    cfg_original = backend.cfg
    filas: list[dict[str, Any]] = []
    try:
        for variante, (sufijo, guia) in variantes.items():
            backend.cfg = (
                cfg_original.model_copy(update={"audioldm_guidance": guia})
                if guia is not None
                else cfg_original
            )
            for historia, escena in escenas:
                modificada = con_sufijo(escena, sufijo)
                for seed in seeds:
                    inicio = time.perf_counter()
                    crudo, frecuencia = backend.generar(modificada, duracion_s, seed)
                    audio = a_mono(crudo)
                    problema = problema_de_ambiente(audio, frecuencia)
                    filas.append(
                        {
                            "variante": variante,
                            "historia": historia,
                            "escena": escena.numero,
                            "seed": seed,
                            "guidance": backend.cfg.audioldm_guidance,
                            "prompt_efectivo": preparar_prompt_audio(modificada.prompt_sonido),
                            "nivel_dbfs": round(nivel_dbfs(audio), 1),
                            "fraccion_silencio": round(fraccion_en_silencio(audio, frecuencia), 3),
                            "apto": problema is None,
                            "problema": problema or "",
                            "segundos": round(time.perf_counter() - inicio, 2),
                        }
                    )
                    if carpeta is not None:
                        destino = (
                            carpeta / variante / f"{historia[:15]}_e{escena.numero}_s{seed}.wav"
                        )
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        sf.write(str(destino), audio, frecuencia, subtype="PCM_16")
                log.info(
                    "ablacion_escena",
                    extra=kv(variante=variante, historia=historia[:24], escena=escena.numero),
                )
    finally:
        backend.cfg = cfg_original
    return filas


def resumir(filas: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Por variante: clips aptos, escenas que pasan (alguna seed apta) y nivel mediano."""
    grupos: dict[str, list[Mapping[str, Any]]] = {}
    for fila in filas:
        grupos.setdefault(str(fila["variante"]), []).append(fila)
    resumen = []
    for variante, grupo in grupos.items():
        escenas: dict[tuple[str, int], bool] = {}
        for f in grupo:
            clave = (str(f["historia"]), int(f["escena"]))
            escenas[clave] = escenas.get(clave, False) or bool(f["apto"])
        resumen.append(
            {
                "variante": variante,
                "clips": len(grupo),
                "clips_aptos": sum(1 for f in grupo if f["apto"]),
                "escenas": len(escenas),
                "escenas_que_pasan": sum(escenas.values()),
                "nivel_dbfs_mediana": round(statistics.median(f["nivel_dbfs"] for f in grupo), 1),
                "segundos_por_clip": round(statistics.mean(f["segundos"] for f in grupo), 2),
            }
        )
    return resumen


def reporte_md(filas: Sequence[Mapping[str, Any]], bateria: str) -> str:
    lineas = [
        "# AudioLDM: variantes de prompt y guidance (complemento de 6.2)",
        "",
        f"Prompts: los `prompt_sonido` de la batería `{bateria}`. "
        f"Seeds: {', '.join(map(str, SEEDS))}.",
        "Una escena pasa si alguna de sus 2 seeds da un clip apto (como en producción).",
        "",
        "| Variante | Escenas que pasan | Clips aptos | Nivel mediano | s/clip |",
        "|---|---|---|---|---|",
    ]
    for r in resumir(filas):
        lineas.append(
            f"| `{r['variante']}` | {r['escenas_que_pasan']}/{r['escenas']} "
            f"| {r['clips_aptos']}/{r['clips']} | {r['nivel_dbfs_mediana']} dBFS "
            f"| {r['segundos_por_clip']} |"
        )
    variantes = list(dict.fromkeys(str(f["variante"]) for f in filas))
    por_clave: dict[tuple[str, int], dict[str, list[Mapping[str, Any]]]] = {}
    for f in filas:
        clave = (str(f["historia"]), int(f["escena"]))
        por_clave.setdefault(clave, {}).setdefault(str(f["variante"]), []).append(f)
    lineas += [
        "",
        "## Por escena (mejor nivel de las 2 seeds; ✗ = ninguna apta)",
        "",
        "| Historia | Esc. | Prompt (base) | " + " | ".join(f"`{v}`" for v in variantes) + " |",
        "|---|---|---|" + "---|" * len(variantes),
    ]
    for (historia, numero), por_variante in por_clave.items():
        base = next(iter(por_variante.values()))[0]["prompt_efectivo"]
        celdas = []
        for v in variantes:
            grupo = por_variante.get(v, [])
            mejor = max((f["nivel_dbfs"] for f in grupo), default=None)
            marca = "" if any(f["apto"] for f in grupo) else " ✗"
            celdas.append("—" if mejor is None else f"{mejor}{marca}")
        lineas.append(
            f"| {historia[16:40]} | {numero} | {base[:70]} | " + " | ".join(celdas) + " |"
        )
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--bateria", type=Path, help="carpeta de la batería (por defecto, la última)"
    )
    parser.add_argument("--perfil", default="rapido")
    args = parser.parse_args(argv)
    setup_logging()
    from storybook.sound.generator import crear_backend

    bateria = args.bateria or ultima_bateria()
    escenas = recolectar_escenas(bateria)
    if not escenas:
        sys.stdout.write(f"No hay historias en {bateria / 'c3_ipadapter'}.\n")
        return 1
    cfg = config.load_config(args.perfil)
    backend = crear_backend("audioldm", cfg.sound)
    backend.cargar()
    try:
        filas = ablacion(
            backend, escenas, cfg.sound.duration_s, carpeta=bateria / "audioldm_prompts"
        )
    finally:
        backend.liberar()

    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    texto = reporte_md(filas, bateria.name)
    (EVIDENCIAS / "f6_audioldm_prompts.md").write_text(texto, encoding="utf-8")
    datos = {"bateria": bateria.name, "resumen": resumir(filas), "clips": filas}
    (EVIDENCIAS / "f6_audioldm_prompts.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sys.stdout.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
