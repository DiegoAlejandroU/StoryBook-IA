"""Batería de experimentos (tareas 6.1 y 6.2): consistencia visual, pasos de difusión y sonido.

Para cada idea (por defecto 4: terror, fantasía, ciencia ficción e infantil, CLAUDE.md §13):

1. **Historia completa** con la configuración de producción (``experiments/c3_ipadapter``:
   Story Bible + seed fija + IP-Adapter 0.4, LCM 6 pasos, AudioLDM con respaldo procedural).
   Se miden los tiempos por etapa, la VRAM pico, CLIP y el WER de la narración.
2. **Variantes de imagen** sobre el mismo texto (la Bible de la historia completa, sin
   seeds): C1 línea base, C2 Bible sin IP-Adapter y ``calidad`` (DPM++ 25 pasos). Así la
   única diferencia entre configuraciones es la estrategia de imagen.

Cada prueba agrega una fila a ``experiments/results.csv`` y deja su hoja de contactos. El
resumen en Markdown y las hojas van a ``docs/evidencias/`` para versionarlos. Las columnas
``*_1a5`` (lista de 4 dimensiones del enunciado) se llenan a mano después.

Uso (PowerShell, desde la carpeta del proyecto; Ollama abierto):
    uv run python scripts/run_experiment.py                  # 4 ideas, C3 + C1, C2, calidad
    uv run python scripts/run_experiment.py --ideas 2 --variantes experiments/c1_baseline
    uv run python scripts/run_experiment.py --completa experiments/llm_8b --variantes
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Protocol

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.evaluation.contact_sheet import hoja_de_contactos
from storybook.evaluation.report import agregar_filas, reporte_md
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.schemas import StoryBible
from storybook.storage import (
    NUM_ESCENAS,
    HistoriaGuardada,
    cargar_bible,
    guardar_bible,
    guardar_json,
)

log = get_logger("run_experiment")

IDEAS: Final = (
    ("Una casa antigua donde todos los relojes se detienen a medianoche", "terror"),
    ("El último dragón vive escondido en una biblioteca", "fantasia"),
    ("Una astronauta despierta sola en una estación espacial a la deriva", "ciencia_ficcion"),
    ("Un perro y un gato deben cruzar la ciudad para volver a casa", "infantil"),
)
COMPLETA: Final = "experiments/c3_ipadapter"
VARIANTES: Final = ("experiments/c1_baseline", "experiments/c2_bible", "calidad")
RESULTADOS: Final = config.PROJECT_ROOT / "experiments" / "results.csv"
RUNS: Final = config.PROJECT_ROOT / "experiments" / "runs"
EVIDENCIAS: Final = config.DOCS_DIR / "evidencias"
TIPO_VARIANTE: Final = "storybook_variante_imagen"


class Puntuador(Protocol):
    def imagen_texto(self, imagen: Path, texto: str) -> float: ...

    def imagen_imagen(self, rutas: list[Path]) -> dict[str, float]: ...


class VerificadorVoz(Protocol):
    def evaluar(self, wav: Path, texto_referencia: str) -> Any: ...


def nombre_config(perfil: str) -> str:
    return Path(perfil).name


def bible_sin_seeds(bible: StoryBible) -> StoryBible:
    """La misma historia sin seeds: cada variante las asigna según su ``consistency``."""
    return bible.model_copy(
        update={
            "personajes": [p.model_copy(update={"seed": None}) for p in bible.personajes],
            "escenas": [e.model_copy(update={"seed_imagen": None}) for e in bible.escenas],
        }
    )


# ---------------------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------------------
def metricas_clip(
    puntuador: Puntuador | None, imagenes: Sequence[tuple[Path, str, bool]]
) -> dict[str, float | None]:
    """CLIP sobre las ilustraciones reales (sin las de respaldo): (ruta, prompt, respaldo)."""
    vacio: dict[str, float | None] = {"media": None, "minimo": None, "texto": None}
    validas = [(r, p) for r, p, respaldo in imagenes if not respaldo and r.is_file()]
    if puntuador is None or not validas:
        return vacio
    textos = [puntuador.imagen_texto(r, p) for r, p in validas]
    resultado = dict(vacio, texto=round(statistics.mean(textos), 4))
    if len(validas) >= 2:
        pares = puntuador.imagen_imagen([r for r, _ in validas])
        resultado.update(media=pares["media"], minimo=pares["minimo"])
    return resultado


def wer_historia(
    verificador: VerificadorVoz | None, bible: StoryBible, carpeta: Path
) -> float | None:
    if verificador is None:
        return None
    wers = []
    for escena in bible.escenas:
        wav = carpeta / f"voice_{escena.numero}.wav"
        if wav.is_file():
            wers.append(float(verificador.evaluar(wav, escena.texto_narrativo).wer))
    return round(statistics.mean(wers), 4) if wers else None


def vram_pico(datos: Any) -> float | None:
    """Máximo de ``vram_gpu_pico_mb`` en cualquier parte del manifest o de una etapa."""
    valores: list[float] = []

    def recorrer(nodo: Any) -> None:
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if clave == "vram_gpu_pico_mb" and isinstance(valor, int | float):
                    valores.append(float(valor))
                else:
                    recorrer(valor)
        elif isinstance(nodo, list):
            for elemento in nodo:
                recorrer(elemento)

    recorrer(datos)
    return round(max(valores), 1) if valores else None


def describir_imagen(parametros: dict[str, Any]) -> str:
    texto = f"{parametros.get('scheduler')} {parametros.get('pasos')} pasos"
    if parametros.get("ip_adapter"):
        texto += f", IP-Adapter {parametros.get('ip_adapter_scale')}"
    if not parametros.get("usar_bible", True):
        texto += ", sin Bible"
    return texto


def describir_sonido(manifest: dict[str, Any]) -> str:
    sonidos = manifest.get("etapas", {}).get("sonido", {}).get("sonidos", [])
    conteo: dict[str, int] = {}
    for sonido in sonidos:
        conteo[sonido.get("backend", "?")] = conteo.get(sonido.get("backend", "?"), 0) + 1
    return " · ".join(f"{b} {n}/{NUM_ESCENAS}" for b, n in conteo.items())


def _seed_base(cfg: config.AppConfig) -> int | str:
    return cfg.consistency.base_seed if cfg.consistency.fixed_seed else "aleatoria"


# ---------------------------------------------------------------------------------------
# Filas de results.csv
# ---------------------------------------------------------------------------------------
def fila_completa(
    id_prueba: str,
    configuracion: str,
    historia: HistoriaGuardada,
    clip: dict[str, float | None],
    wer: float | None,
) -> dict[str, Any]:
    m = historia.manifest
    segundos = m.get("segundos", {})
    etapa_img = m.get("etapas", {}).get("imagen", {})
    cfg = m.get("configuracion", {})
    return {
        "id": id_prueba,
        "fecha": m.get("creado"),
        "idea": m.get("idea"),
        "genero": m.get("genero"),
        "configuracion": configuracion,
        "perfil": m.get("perfil"),
        "llm": m.get("etapas", {}).get("texto", {}).get("modelo"),
        "imagen": describir_imagen(etapa_img.get("parametros", {})),
        "voz": cfg.get("voice", {}).get("piper_voice"),
        "sonido": describir_sonido(m),
        "seed_base": cfg.get("consistency", {}).get("base_seed"),
        "t_llm_s": segundos.get("texto"),
        "t_imagen_s": segundos.get("imagen"),
        "t_voz_s": segundos.get("voz"),
        "t_sonido_s": segundos.get("sonido"),
        "t_mezcla_s": segundos.get("mezcla"),
        "t_total_s": segundos.get("total"),
        "vram_pico_mb": vram_pico(m.get("etapas", {})),
        "clip_img_img_media": clip["media"],
        "clip_img_img_min": clip["minimo"],
        "clip_img_txt_media": clip["texto"],
        "wer_medio": wer,
        "escenas_completas": sum(historia.escena(n).completa for n in range(1, NUM_ESCENAS + 1)),
        "fallbacks": "; ".join(m.get("fallbacks", [])),
        "fallos": "; ".join(m.get("errores", [])),
        "cambios": f"historia completa en {historia.carpeta.name}",
    }


def fila_variante(
    id_prueba: str,
    configuracion: str,
    cfg: config.AppConfig,
    base: dict[str, Any],
    etapa: Any,
    segundos: float,
    clip: dict[str, float | None],
) -> dict[str, Any]:
    return {
        "id": id_prueba,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "idea": base["idea"],
        "genero": base["genero"],
        "configuracion": configuracion,
        "perfil": cfg.profile,
        "llm": base["llm"],
        "imagen": describir_imagen(etapa.parametros),
        "seed_base": _seed_base(cfg),
        "t_imagen_s": round(segundos, 2),
        "vram_pico_mb": vram_pico([m.as_dict() for m in etapa.metricas]),
        "clip_img_img_media": clip["media"],
        "clip_img_img_min": clip["minimo"],
        "clip_img_txt_media": clip["texto"],
        "escenas_completas": sum(1 for r in etapa.imagenes if not r.respaldo),
        "fallbacks": "; ".join(etapa.fallbacks),
        "fallos": "; ".join(etapa.errores),
        "cambios": f"solo imágenes, con el texto de {base['id']}",
    }


def fila_fallida(id_prueba: str, configuracion: str, idea: str, genero: str, error: str) -> dict:
    return {
        "id": id_prueba,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "idea": idea,
        "genero": genero,
        "configuracion": configuracion,
        "escenas_completas": 0,
        "fallos": error[:300],
    }


# ---------------------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------------------
def correr_variante(
    cfg: config.AppConfig, bible: StoryBible, carpeta: Path, backend_imagen: Any = None
) -> tuple[Any, float]:
    from storybook.image.generator import GeneradorImagenes

    inicio = time.perf_counter()
    etapa = GeneradorImagenes(cfg.image, cfg.consistency, backend_imagen).generar(
        bible_sin_seeds(bible), carpeta
    )
    segundos = time.perf_counter() - inicio
    guardar_bible(carpeta, etapa.bible)  # con las seeds de esta variante
    guardar_json(
        carpeta / "manifest.json",
        {
            "tipo": TIPO_VARIANTE,
            "perfil": cfg.profile,
            "creado": datetime.now().isoformat(timespec="seconds"),
            "segundos": round(segundos, 2),
            "configuracion": cfg.model_dump(mode="json"),
            "etapas": {"imagen": etapa.a_dict()},
        },
    )
    return etapa, segundos


def _imagenes_manifest(carpeta: Path, manifest: dict[str, Any]) -> list[tuple[Path, str, bool]]:
    imagenes = manifest.get("etapas", {}).get("imagen", {}).get("imagenes", [])
    return [
        (carpeta / i["archivo"], i.get("prompt", {}).get("prompt", ""), bool(i.get("respaldo")))
        for i in imagenes
    ]


def ejecutar_bateria(
    ideas: Sequence[tuple[str, str]],
    completa: str = COMPLETA,
    variantes: Sequence[str] = VARIANTES,
    raiz: Path | None = None,
    *,
    dependencias: Any = None,
    puntuador: Callable[[], Puntuador | None] | None = None,
    verificador: Callable[[], VerificadorVoz | None] | None = None,
    id_experimento: str | None = None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Corre la batería. Devuelve las filas para results.csv y las hojas de contactos."""
    from storybook.pipeline import Pipeline

    id_experimento = id_experimento or datetime.now().strftime("%Y%m%d_%H%M%S")
    raiz = raiz or RUNS / id_experimento
    cache: dict[str, Any] = {}

    def obtener(clave: str, fabrica: Callable[[], Any] | None) -> Any:
        if clave not in cache:
            cache[clave] = fabrica() if fabrica else None
        return cache[clave]

    filas: list[dict[str, Any]] = []
    hojas: list[Path] = []
    nombre_completa = nombre_config(completa)
    for indice, (idea, genero) in enumerate(ideas, start=1):
        id_base = f"{id_experimento}_{indice}"
        log.info("experimento_idea", extra=kv(indice=indice, idea=idea, genero=genero))
        try:
            pipeline = Pipeline(config.load_config(completa), dependencias, raiz / nombre_completa)
            historia = pipeline.generar(idea, genero)
        except Exception as exc:  # se registra y se sigue con la siguiente idea
            log.exception("experimento_completa_fallida", extra=kv(idea=idea))
            error = f"{type(exc).__name__}: {exc}"
            filas.append(
                fila_fallida(f"{id_base}_{nombre_completa}", nombre_completa, idea, genero, error)
            )
            continue
        clip = metricas_clip(
            obtener("clip", puntuador), _imagenes_manifest(historia.carpeta, historia.manifest)
        )
        wer = wer_historia(obtener("wer", verificador), historia.bible, historia.carpeta)
        base = fila_completa(f"{id_base}_{nombre_completa}", nombre_completa, historia, clip, wer)
        filas.append(base)
        hojas.append(
            hoja_de_contactos(historia.carpeta, titulo=f"{historia.titulo} · {nombre_completa}")
        )
        bible = cargar_bible(historia.carpeta)

        for perfil in variantes:
            nombre = nombre_config(perfil)
            id_prueba = f"{id_base}_{nombre}"
            carpeta = raiz / nombre / historia.carpeta.name
            try:
                cfg = config.load_config(perfil)
                backend = dependencias.backend_imagen if dependencias else None
                etapa, segundos = correr_variante(cfg, bible, carpeta, backend)
            except Exception as exc:
                log.exception("experimento_variante_fallida", extra=kv(variante=perfil))
                filas.append(
                    fila_fallida(id_prueba, nombre, idea, genero, f"{type(exc).__name__}: {exc}")
                )
                continue
            imagenes = [(r.ruta, r.prompt.prompt, r.respaldo) for r in etapa.imagenes]
            clip = metricas_clip(obtener("clip", puntuador), imagenes)
            filas.append(fila_variante(id_prueba, nombre, cfg, base, etapa, segundos, clip))
            hojas.append(hoja_de_contactos(carpeta, titulo=f"{historia.titulo} · {nombre}"))
    return filas, hojas


def puntuador_real() -> Puntuador:
    from storybook.evaluation.clip_metrics import ClipScorer

    e = config.load_config().evaluation
    return ClipScorer(e.clip_model, e.clip_pretrained)


def verificador_real() -> VerificadorVoz:
    from storybook.evaluation.asr_check import WhisperChecker

    e = config.load_config().evaluation
    return WhisperChecker(
        e.whisper_model, e.whisper_compute_type, e.whisper_language, e.cpu_threads
    )


def guardar_evidencias(
    filas: Sequence[dict[str, Any]],
    hojas: Sequence[Path],
    id_experimento: str,
    destino: Path = EVIDENCIAS,
) -> Path:
    """Resumen en Markdown y copia de las hojas de contactos (versionables)."""
    carpeta_hojas = destino / "f6_hojas"
    carpeta_hojas.mkdir(parents=True, exist_ok=True)
    copias = []
    for hoja in hojas:
        nombre = f"{id_experimento}_{hoja.parent.name[:24]}_{hoja.parent.parent.name}.jpg"
        shutil.copy2(hoja, carpeta_hojas / nombre)
        copias.append(nombre)
    texto = reporte_md(
        [{k: "" if v is None else str(v) for k, v in f.items()} for f in filas],
        f"Batería de experimentos {id_experimento}",
    )
    texto += "\n## Hojas de contactos\n\n" + "\n".join(f"- `f6_hojas/{c}`" for c in copias) + "\n"
    ruta = destino / f"f6_experimentos_{id_experimento}.md"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ideas", type=int, default=len(IDEAS), choices=range(1, len(IDEAS) + 1))
    parser.add_argument("--completa", default=COMPLETA, help="perfil de la historia completa")
    parser.add_argument("--variantes", nargs="*", default=list(VARIANTES))
    parser.add_argument("--sin-clip", action="store_true")
    parser.add_argument("--sin-wer", action="store_true")
    args = parser.parse_args(argv)
    setup_logging()

    id_experimento = datetime.now().strftime("%Y%m%d_%H%M%S")
    filas, hojas = ejecutar_bateria(
        IDEAS[: args.ideas],
        args.completa,
        args.variantes,
        puntuador=None if args.sin_clip else puntuador_real,
        verificador=None if args.sin_wer else verificador_real,
        id_experimento=id_experimento,
    )
    agregar_filas(RESULTADOS, filas)
    resumen = guardar_evidencias(filas, hojas, id_experimento)
    fallidas = [f for f in filas if f.get("escenas_completas") == 0]
    sys.stdout.write(resumen.read_text(encoding="utf-8"))
    sys.stdout.write(
        f"\n{len(filas)} pruebas ({len(fallidas)} fallidas) agregadas a {RESULTADOS}.\n"
        f"Resumen: {resumen}\n"
    )
    return 2 if fallidas or not filas else 0


if __name__ == "__main__":
    sys.exit(main())
