"""Voz XTTS-v2 y ambiente Stable Audio Open del perfil Avanzada (18 nov), medidos aparte.

Narra y ambienta las escenas de una historia guardada con la configuración ``avanzada`` y
deja los audios, tiempos y el backend que respondió en ``docs/evidencias/f10_voz_sonido.*``
y ``docs/evidencias/f10_audio/``. Si XTTS o Stable Audio no están, el informe muestra a qué
respaldo pasó (Piper, AudioLDM...), igual que haría la app.

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/f10_voz_sonido.py
    uv run python scripts/f10_voz_sonido.py --historia outputs/<carpeta> --escenas 1 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from storybook import config
from storybook.gpu import free_cuda_memory
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.storage import cargar_bible, listar_historias

log = get_logger("f10_voz_sonido")
EVIDENCIAS = config.DOCS_DIR / "evidencias"


def historia_reciente() -> Path:
    for entrada in listar_historias([config.OUTPUTS_DIR]):
        return entrada.carpeta
    raise FileNotFoundError(f"No hay historias guardadas en {config.OUTPUTS_DIR}")


def medir_voz(perfil: str, bible: Any, carpeta: Path, escenas: list[int]) -> dict[str, Any]:
    from storybook.voice.tts import Narrador

    cfg = config.load_config(perfil)
    inicio = time.perf_counter()
    try:
        etapa = Narrador(cfg.voice).narrar_bible(bible, carpeta, escenas)
    except Exception as exc:
        log.exception("voz_fallida")
        return {"error": f"{type(exc).__name__}: {exc}"[:400]}
    return {
        "backend": etapa.backend,
        "segundos_total": round(time.perf_counter() - inicio, 2),
        "carga_s": next((m.segundos for m in etapa.metricas if m.etapa == "voz_carga"), None),
        "escenas": [n.a_dict() for n in etapa.narraciones],
    }


def medir_sonido(perfil: str, bible: Any, carpeta: Path, escenas: list[int]) -> dict[str, Any]:
    from storybook.sound.generator import GeneradorSonido

    cfg = config.load_config(perfil)
    inicio = time.perf_counter()
    try:
        etapa = GeneradorSonido(cfg.sound, cfg.consistency.base_seed).generar(
            bible, carpeta, escenas
        )
    except Exception as exc:
        log.exception("sonido_fallido")
        return {"error": f"{type(exc).__name__}: {exc}"[:400]}
    finally:
        free_cuda_memory()
    return {
        "cadena": list(cfg.sound.backends),
        "segundos_total": round(time.perf_counter() - inicio, 2),
        "fallbacks": etapa.fallbacks,
        "errores": etapa.errores,
        "escenas": [s.a_dict() for s in etapa.sonidos],
        "metricas": [m.as_dict() for m in etapa.metricas],
    }


def reporte_md(historia: Path, voz: dict[str, Any], sonido: dict[str, Any]) -> str:
    lineas = [
        f"# f10: voz y ambiente del perfil Avanzada ({time.strftime('%Y-%m-%d %H:%M')})",
        "",
        f"Historia: `{historia.name}`. Audios en `docs/evidencias/f10_audio/`.",
        "",
        "## Voz",
        "",
    ]
    if "error" in voz:
        lineas.append(f"Falló: {voz['error']}")
    else:
        b = voz["backend"]
        respaldo = f" (respaldo: XTTS falló: {b['error_xtts']})" if b.get("error_xtts") else ""
        lineas += [
            f"Backend: **{b.get('backend')}** {b.get('voz', '')} en {b.get('dispositivo')}"
            f"{respaldo}. Carga: {voz['carga_s']} s.",
            "",
            "| Escena | Audio (s) | Síntesis (s) | RTF |",
            "|---|---|---|---|",
        ]
        for n in voz["escenas"]:
            lineas.append(
                f"| {n['escena']} | {n['duracion_s']} | {n['segundos_sintesis']} | {n.get('rtf')} |"
            )
    lineas += ["", "## Ambiente", ""]
    if "error" in sonido:
        lineas.append(f"Falló: {sonido['error']}")
    else:
        lineas += [
            f"Cadena: {' → '.join(sonido['cadena'])}. Total: {sonido['segundos_total']} s. "
            f"Respaldos: {', '.join(sonido['fallbacks']) or 'ninguno'}.",
            "",
            "| Escena | Backend | Prompt |",
            "|---|---|---|",
        ]
        for s in sonido["escenas"]:
            lineas.append(
                f"| {s.get('escena')} | {s.get('backend')} | {str(s.get('prompt'))[:90]} |"
            )
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--historia", type=Path)
    parser.add_argument("--perfil", default="avanzada")
    parser.add_argument("--escenas", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--solo-voz", action="store_true")
    parser.add_argument("--solo-sonido", action="store_true")
    args = parser.parse_args(argv)
    setup_logging()

    historia = args.historia or historia_reciente()
    bible = cargar_bible(historia)
    carpeta = EVIDENCIAS / "f10_audio" / historia.name
    carpeta.mkdir(parents=True, exist_ok=True)
    voz: dict[str, Any] = {"error": "no medida (--solo-sonido)"}
    sonido: dict[str, Any] = {"error": "no medido (--solo-voz)"}
    if not args.solo_sonido:
        voz = medir_voz(args.perfil, bible, carpeta, args.escenas)
        log.info("voz_lista", extra=kv(backend=voz.get("backend"), error=voz.get("error")))
    if not args.solo_voz:
        sonido = medir_sonido(args.perfil, bible, carpeta, args.escenas)
        log.info(
            "sonido_listo", extra=kv(fallbacks=sonido.get("fallbacks"), error=sonido.get("error"))
        )
    nombre = "f10_voz" if args.solo_voz else "f10_sonido" if args.solo_sonido else "f10_voz_sonido"

    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    datos = {"historia": historia.name, "perfil": args.perfil, "voz": voz, "sonido": sonido}
    (EVIDENCIAS / f"{nombre}.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (EVIDENCIAS / f"{nombre}.md").write_text(reporte_md(historia, voz, sonido), encoding="utf-8")
    medidas = ([] if args.solo_sonido else [voz]) + ([] if args.solo_voz else [sonido])
    if any("error" in m for m in medidas):
        return 1
    # Con --solo-voz, que narre Piper (respaldo) también es un fallo: se quería probar XTTS.
    respaldo = voz.get("backend", {}).get("respaldo_de") if not args.solo_sonido else None
    return 1 if args.solo_voz and respaldo else 0


if __name__ == "__main__":
    sys.exit(main())
