"""F1 · Tarea 1.4: generaciones reales de la Story Bible con el LLM local (Ollama).

Para N combinaciones de idea y género (todos los géneros del enunciado) genera la Story Bible
con el planificador del proyecto y, si ``llm.auditar`` está activo, la audita y corrige. Mide:
validez, intentos (reintentos por validación) y sus causas, tiempo, tokens por segundo, fracción
del modelo en GPU y contradicciones encontradas por el auditor.

Salidas:
- ``outputs/f1/<fecha_hora>/``: ``story_XX.json``, ``llamadas_XX.json``, ``run.log`` y, si una
  generación falla, ``fallo_XX.json`` (errores de cada intento y la última salida del modelo).
- ``docs/evidencias/f1_generaciones.csv`` y ``docs/evidencias/f1_resumen.md`` (van al informe);
  con otro perfil llevan sufijo, p. ej. ``f1_resumen_calidad.md``, para no pisar los del 4B.

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/f1_generaciones.py --n 10
    uv run python scripts/f1_generaciones.py --n 3 --num-gpu 20        # otro reparto GPU/CPU
    uv run python scripts/f1_generaciones.py --n 3 --perfil experiments/llm_8b   # Qwen3 8B
    uv run python scripts/f1_generaciones.py --n 3 --estrategia una_llamada --sin-auditor
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.schemas import validar_entrada
from storybook.story.llm_client import LLMError, LLMValidationError, OllamaClient

log = get_logger("f1_generaciones")

# Una idea por fila; cubre los seis géneros del enunciado (se repiten de a dos).
IDEAS: tuple[tuple[str, str], ...] = (
    ("Un faro abandonado que se enciende solo cada noche", "misterio"),
    ("Una niña descubre que su sombra tiene vida propia", "fantasia"),
    ("Un robot jardinero cuida la última huerta de una estación espacial", "ciencia_ficcion"),
    ("Una casa que cambia de habitaciones mientras todos duermen", "terror"),
    ("Un perro y un gato deben cruzar la ciudad para volver a casa", "infantil"),
    ("Dos hermanos buscan el tesoro de su abuelo en la selva", "aventura"),
    ("Un reloj de bolsillo retrocede un minuto cada vez que alguien miente", "misterio"),
    ("El último dragón vive escondido en una biblioteca", "fantasia"),
    ("Una señal de radio llega desde una ciudad que no aparece en los mapas", "ciencia_ficcion"),
    ("Una muñeca antigua aparece cada mañana en un lugar distinto", "terror"),
)

COLUMNAS = (
    "n",
    "genero",
    "idea",
    "valida",
    "estrategia",
    "modelo",
    "llamadas",
    "intentos",
    "segundos_plan",
    "segundos_auditor",
    "segundos_total",
    "tokens_salida",
    "tokens_por_s",
    "fraccion_gpu",
    "contradicciones",
    "escenas_regeneradas",
    "palabras_min",
    "palabras_max",
    "titulo",
    "causas_reintento",
    "error",
)

# Palabra clave del mensaje de validación -> causa legible (el orden importa).
_CATEGORIAS: tuple[tuple[str, str], ...] = (
    ("palabras", "longitud"),
    ("tokens CLIP", "presupuesto CLIP"),
    ("inexistentes", "id de personaje"),
    ("inglés", "idioma"),
    ("fase", "fase"),
    ("protagonista", "protagonista"),
)


def causa_reintento(error: str) -> str:
    """'personajes.0.descripcion_visual_fija: Value error, ... tokens CLIP ...' ->
    'personajes.descripcion_visual_fija · presupuesto CLIP'."""
    campo, separador, mensaje = error.partition(": ")
    if not separador or " " in campo:  # error del modelo completo, sin campo
        campo, mensaje = "(modelo)", error
    campo = re.sub(r"\.\d+", "", campo)
    categoria = next((c for clave, c in _CATEGORIAS if clave in mensaje), "otro")
    return f"{campo} · {categoria}"


def _causas(errores_por_llamada: list[list[list[str]]]) -> Counter[str]:
    return Counter(
        causa_reintento(error)
        for errores_por_intento in errores_por_llamada
        for errores in errores_por_intento
        for error in errores
    )


def sufijo_evidencias(perfil: str) -> str:
    """El perfil de la sustentación (rapido) no lleva sufijo; los demás, sí."""
    return "" if perfil == "rapido" else f"_{Path(perfil).stem}"


def _tokens(llamadas: list[Any]) -> tuple[int, float]:
    tokens = sum(r.output_tokens for r in llamadas)
    segundos = sum(r.segundos for r in llamadas)
    return tokens, round(tokens / segundos, 2) if segundos else 0.0


def generar_una(
    n: int,
    idea: str,
    genero: str,
    cliente: OllamaClient,
    cfg_llm: config.LLMConfig,
    auditar: bool,
    carpeta: Path,
) -> dict[str, Any]:
    from storybook.story.auditor import Auditor
    from storybook.story.planner import Planificador

    fila: dict[str, Any] = dict.fromkeys(COLUMNAS, "")
    fila.update(n=n, genero=genero, idea=idea, estrategia=cfg_llm.estrategia, modelo=cfg_llm.model)
    inicio = time.perf_counter()
    llamadas: list[Any] = []
    planificador = Planificador(cliente, cfg_llm)
    errores_fallidos: list[list[str]] = []  # intentos de la llamada que agotó los reintentos
    try:
        solicitud = validar_entrada(idea, genero)
        plan = planificador.generar(solicitud, cfg_llm.estrategia)
        bible = plan.bible
        llamadas.extend(plan.llamadas)
        fila["segundos_plan"] = round(plan.segundos_totales, 2)
        if auditar:
            t_aud = time.perf_counter()
            auditoria = Auditor(cliente, cfg_llm).auditar_y_corregir(bible)
            bible = auditoria.bible
            llamadas.extend(auditoria.llamadas)
            fila["segundos_auditor"] = round(time.perf_counter() - t_aud, 2)
            fila["contradicciones"] = sum(len(a.contradicciones) for a in auditoria.auditorias)
            fila["escenas_regeneradas"] = " ".join(map(str, auditoria.escenas_regeneradas))
        palabras = [len(e.texto_narrativo.split()) for e in bible.escenas]
        fila.update(
            valida=True,
            titulo=bible.titulo,
            palabras_min=min(palabras),
            palabras_max=max(palabras),
        )
        (carpeta / f"story_{n:02d}.json").write_text(
            bible.model_dump_json(indent=2), encoding="utf-8"
        )
    except (LLMError, ValueError) as exc:
        fila.update(valida=False, error=f"{type(exc).__name__}: {exc}"[:300])
        log.warning("generacion_fallida", extra=kv(n=n, error=fila["error"]))
        if not llamadas:  # el plan o una escena fallaron: se miden las llamadas completadas
            llamadas.extend(planificador.registro)
        if isinstance(exc, LLMValidationError):
            errores_fallidos = exc.errores_por_intento
            (carpeta / f"fallo_{n:02d}.json").write_text(
                json.dumps(
                    {
                        "error": str(exc),
                        "errores_por_intento": exc.errores_por_intento,
                        "ultimo_contenido": exc.ultimo_contenido,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    tokens, por_s = _tokens(llamadas)
    causas = _causas([r.errores_por_intento for r in llamadas] + [errores_fallidos])
    fila["_causas"] = causas
    fila["causas_reintento"] = "; ".join(f"{c} ×{n}" for c, n in causas.most_common())
    fila.update(
        llamadas=len(llamadas) + (1 if errores_fallidos else 0),
        intentos=sum(r.intentos for r in llamadas) + len(errores_fallidos),
        tokens_salida=tokens,
        tokens_por_s=por_s,
        segundos_total=round(time.perf_counter() - inicio, 2),
    )
    try:
        fila["fraccion_gpu"] = cliente.gpu_fraction(cfg_llm.model)
    except LLMError:
        fila["fraccion_gpu"] = ""
    (carpeta / f"llamadas_{n:02d}.json").write_text(
        json.dumps([r.a_dict() for r in llamadas], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("generacion", extra=kv(**{k: fila[k] for k in COLUMNAS if k not in ("idea",)}))
    return fila


def resumen_md(filas: list[dict[str, Any]], args: argparse.Namespace, cfg_llm: Any) -> str:
    validas = [f for f in filas if f["valida"] is True]
    tiempos = [f["segundos_total"] for f in filas]
    tok_s = [f["tokens_por_s"] for f in filas if f["tokens_por_s"]]
    intentos_por_llamada = [f["intentos"] / f["llamadas"] for f in filas if f["llamadas"]]
    fracciones = [f["fraccion_gpu"] for f in filas if isinstance(f["fraccion_gpu"], float)]

    def med(valores: list[float]) -> str:
        return f"{statistics.median(valores):.2f}" if valores else "-"

    causas: Counter[str] = Counter()
    for fila in filas:
        causas.update(fila.get("_causas") or {})
    lineas = [
        f"# F1 · Generaciones reales de la Story Bible ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f"- Perfil `{args.perfil}` · modelo `{cfg_llm.model}` · estrategia `{cfg_llm.estrategia}`"
        f" · auditor {'sí' if not args.sin_auditor and cfg_llm.auditar else 'no'}"
        f" · num_ctx {cfg_llm.num_ctx} · num_gpu {cfg_llm.num_gpu or 'auto'}",
        f"- **Story Bibles válidas: {len(validas)}/{len(filas)}**",
        f"- Tiempo por historia (mediana): {med(tiempos)} s · tokens/s (mediana): {med(tok_s)}",
        f"- Intentos por llamada (mediana): {med(intentos_por_llamada)}"
        f" · fracción del modelo en GPU (mediana): {med(fracciones)}",
        "",
        "| # | Género | Válida | Llamadas | Intentos | s total | tok/s | GPU | Contrad. | Título |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for f in filas:
        lineas.append(
            f"| {f['n']} | {f['genero']} | {'sí' if f['valida'] is True else 'NO'} | "
            f"{f['llamadas']} | {f['intentos']} | {f['segundos_total']} | {f['tokens_por_s']} | "
            f"{f['fraccion_gpu']} | {f['contradicciones']} | {f['titulo'] or f['error'][:60]} |"
        )
    if causas:
        lineas += ["", "Causas de reintento (errores de validación devueltos al modelo):", ""]
        lineas += ["| Campo · causa | Veces |", "|---|---:|"]
        lineas += [f"| {causa} | {n} |" for causa, n in causas.most_common()]
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=10, choices=range(1, len(IDEAS) + 1))
    parser.add_argument("--perfil", default="rapido")
    parser.add_argument("--estrategia", choices=["una_llamada", "por_etapas"], default=None)
    parser.add_argument("--num-gpu", type=int, default=None, help="99 = todo el modelo en GPU")
    parser.add_argument("--sin-auditor", action="store_true")
    parser.add_argument("--evidencias", type=Path, default=config.DOCS_DIR / "evidencias")
    args = parser.parse_args(argv)

    carpeta = config.OUTPUTS_DIR / "f1" / datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta.mkdir(parents=True, exist_ok=True)
    setup_logging(log_file=carpeta / "run.log")

    cfg = config.load_config(args.perfil)
    cambios: dict[str, Any] = {}
    if args.estrategia:
        cambios["estrategia"] = args.estrategia
    if args.num_gpu is not None:
        cambios["num_gpu"] = args.num_gpu
    cfg_llm = cfg.llm.model_copy(update=cambios)
    auditar = cfg_llm.auditar and not args.sin_auditor
    log.info("f1_inicio", extra=kv(perfil=args.perfil, n=args.n, salida=str(carpeta), **cambios))

    filas: list[dict[str, Any]] = []
    with OllamaClient(cfg_llm.host, cfg_llm.timeout_s) as cliente:
        if not cliente.has_model(cfg_llm.model):
            log.error("falta_modelo", extra=kv(modelo=cfg_llm.model))
            sys.stdout.write(f"Falta el modelo. Ejecuta: ollama pull {cfg_llm.model}\n")
            return 1
        try:
            for n, (idea, genero) in enumerate(IDEAS[: args.n], start=1):
                filas.append(generar_una(n, idea, genero, cliente, cfg_llm, auditar, carpeta))
        finally:
            try:
                cliente.unload(cfg_llm.model)
            except LLMError as exc:
                log.warning("ollama_unload_fallido", extra=kv(error=str(exc)))

    args.evidencias.mkdir(parents=True, exist_ok=True)
    sufijo = sufijo_evidencias(args.perfil)
    with (args.evidencias / f"f1_generaciones{sufijo}.csv").open(
        "w", newline="", encoding="utf-8"
    ) as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)
    resumen = resumen_md(filas, args, cfg_llm)
    (args.evidencias / f"f1_resumen{sufijo}.md").write_text(resumen, encoding="utf-8")
    (carpeta / "resumen.md").write_text(resumen, encoding="utf-8")
    sys.stdout.write(resumen)
    validas = sum(1 for f in filas if f["valida"] is True)
    log.info("f1_fin", extra=kv(validas=validas, total=len(filas)))
    return 0 if validas == len(filas) else 2


if __name__ == "__main__":
    sys.exit(main())
