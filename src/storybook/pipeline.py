"""Pipeline de punta a punta: idea → Story Bible → imágenes → voz → sonido → mezcla.

Procesa por etapas (CLAUDE.md §4): cada modelo se carga una vez, hace las 5 escenas y se
libera antes del siguiente, para no pasar de los 4 GB de VRAM. Orden:

1. **Texto** (GPU, Ollama): planificador + auditor. Es la única etapa sin la que no hay
   historia; si falla, la ejecución termina con un mensaje claro.
2. **Imágenes** (GPU): si el modelo no carga, 5 ilustraciones de respaldo (fallback).
3. **Voz** (CPU, Piper).
4. **Sonido** (GPU → CPU): cadena con fallback; procedural garantiza los 5 ambientes.
5. **Mezcla** (CPU): ``ambience_N`` y ``mix_N``. Sin voz no hay mezcla, pero el ambiente
   queda disponible.

Todo queda en ``outputs/<run_id>/`` con ``manifest.json`` (modelos, seeds, parámetros,
hardware, tiempos, VRAM, fallbacks y errores), que se guarda también si algo falla.

Las dependencias reales (Ollama, diffusers, Piper) se pueden reemplazar con
``Dependencias`` (``storybook.mock`` para probar la UI sin GPU, y los tests).
"""

from __future__ import annotations

import platform
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from storybook import __version__, config
from storybook.logging_utils import get_logger, kv
from storybook.schemas import SEED_MAX, StoryBible, StoryRequest, validar_entrada
from storybook.storage import (
    ARCHIVO_MANIFEST,
    NUM_ESCENAS,
    TIPO_MANIFEST,
    HistoriaGuardada,
    cargar_bible,
    cargar_historia,
    cargar_manifest,
    crear_carpeta_run,
    guardar_bible,
    guardar_json,
)

logger = get_logger(__name__)

Progreso = Callable[[str, float, str], None]
EscribirHistoria = Callable[[StoryRequest, config.LLMConfig], tuple[StoryBible, dict[str, Any]]]

# (clave, mensaje para la UI, inicio, fin) de la barra de progreso
ETAPAS: Final = (
    ("texto", "Escribiendo la historia (LLM local)", 0.00, 0.40),
    ("imagen", "Ilustrando las 5 escenas", 0.40, 0.65),
    ("voz", "Narrando", 0.65, 0.72),
    ("sonido", "Creando el ambiente sonoro", 0.72, 0.92),
    ("mezcla", "Mezclando voz y ambiente", 0.92, 1.00),
)
PASO_SEED_REGENERAR: Final = 1_000_003  # primo: cada regeneración da una seed distinta


class PipelineError(Exception):
    """La historia no se pudo generar; el mensaje es apto para mostrar en la UI."""


@dataclass
class Dependencias:
    escribir: EscribirHistoria | None = None
    backend_imagen: Any = None
    backend_voz: Any = None
    fabrica_sonido: Callable[[str], Any] | None = None


def escribir_con_ollama(
    solicitud: StoryRequest, cfg_llm: config.LLMConfig
) -> tuple[StoryBible, dict[str, Any]]:
    """Texto real: planificador + auditor con el LLM local; descarga el modelo al terminar."""
    from storybook.story.auditor import Auditor
    from storybook.story.llm_client import LLMConnectionError, OllamaClient
    from storybook.story.planner import Planificador

    try:
        with OllamaClient(cfg_llm.host, cfg_llm.timeout_s) as cliente:
            if not cliente.has_model(cfg_llm.model):
                raise PipelineError(
                    f"Falta el modelo de texto {cfg_llm.model}. "
                    f"Ejecuta: ollama pull {cfg_llm.model}"
                )
            version = cliente.version()
            try:
                plan = Planificador(cliente, cfg_llm).generar(solicitud)
                bible, llamadas, auditoria = plan.bible, list(plan.llamadas), None
                if cfg_llm.auditar:
                    auditoria = Auditor(cliente, cfg_llm).auditar_y_corregir(bible)
                    bible = auditoria.bible
                    llamadas += auditoria.llamadas
                fraccion_gpu = cliente.gpu_fraction(cfg_llm.model)
            finally:
                cliente.unload(cfg_llm.model)
    except LLMConnectionError as exc:
        raise PipelineError(
            "Ollama no responde en " + cfg_llm.host + ". Abre la aplicación de Ollama y vuelve "
            "a intentarlo."
        ) from exc
    return bible, {
        "modelo": cfg_llm.model,
        "ollama": version,
        "estrategia": plan.estrategia,
        "fraccion_gpu": fraccion_gpu,
        "llamadas": [r.a_dict() for r in llamadas],
        "auditoria": auditoria.a_dict() if auditoria else None,
    }


def _hardware() -> dict[str, Any]:
    from storybook.gpu import NvmlReader

    lector = NvmlReader()
    try:
        gpu = lector.info()
    finally:
        lector.close()
    return {
        "sistema": platform.platform(),
        "python": platform.python_version(),
        "procesador": platform.processor(),
        "gpu": gpu,
    }


class Pipeline:
    def __init__(
        self,
        cfg: config.AppConfig,
        dependencias: Dependencias | None = None,
        raiz: Path | None = None,
    ) -> None:
        self.cfg = cfg
        self.deps = dependencias or Dependencias()
        self.raiz = raiz or config.OUTPUTS_DIR

    # -- utilidades -------------------------------------------------------------------
    @staticmethod
    def _avisar(progreso: Progreso | None, etapa: str, avance: float, mensaje: str) -> None:
        if progreso is not None:
            progreso(etapa, avance, mensaje)
        logger.info("progreso", extra=kv(etapa=etapa, avance=round(avance, 2), mensaje=mensaje))

    def _manifest_base(self, carpeta: Path, solicitud: StoryRequest) -> dict[str, Any]:
        return {
            "tipo": TIPO_MANIFEST,
            "version_app": __version__,
            "run_id": carpeta.name,
            "creado": datetime.now().isoformat(timespec="seconds"),
            "perfil": self.cfg.profile,
            "idea": solicitud.idea,
            "genero": solicitud.genero_efectivo,
            "titulo": None,
            "estado": "en_curso",
            "etapas": {},
            "segundos": {},
            "fallbacks": [],
            "errores": [],
            "hardware": _hardware(),
            "configuracion": self.cfg.model_dump(mode="json"),
            "regeneraciones": [],
        }

    # -- etapas -------------------------------------------------------------------------
    def _imagenes(self, bible: StoryBible, carpeta: Path, manifest: dict[str, Any]) -> StoryBible:
        from storybook.image.generator import (
            FALLBACK_RESPALDO,
            GeneradorImagenes,
            ImageModelError,
            imagen_respaldo,
            nombre_archivo_escena,
        )

        generador = GeneradorImagenes(
            self.cfg.image, self.cfg.consistency, self.deps.backend_imagen
        )
        try:
            etapa = generador.generar(bible, carpeta)
        except ImageModelError as exc:
            bible = generador.asegurar_seeds(bible)
            for escena in bible.escenas:
                imagen_respaldo(self.cfg.image.width, self.cfg.image.height, escena.numero).save(
                    carpeta / nombre_archivo_escena(escena.numero)
                )
            manifest["fallbacks"].append(f"{FALLBACK_RESPALDO}:todas")
            manifest["errores"].append(f"imagen: {exc}")
            manifest["etapas"]["imagen"] = {"error": str(exc)}
            return bible
        manifest["etapas"]["imagen"] = etapa.a_dict()
        manifest["fallbacks"] += etapa.fallbacks
        manifest["errores"] += [f"imagen: {e}" for e in etapa.errores]
        return etapa.bible

    def _voz(self, bible: StoryBible, carpeta: Path, manifest: dict[str, Any], numeros: Any = None):
        from storybook.voice.tts import Narrador, TTSError

        try:
            etapa = Narrador(self.cfg.voice, self.deps.backend_voz).narrar_bible(
                bible, carpeta, numeros
            )
        except TTSError as exc:
            manifest["fallbacks"].append("voz:sin_narracion")
            manifest["errores"].append(f"voz: {exc}")
            manifest["etapas"]["voz"] = {"error": str(exc)}
            return None
        manifest["etapas"]["voz"] = etapa.a_dict()
        return etapa

    def _sonido(
        self,
        bible: StoryBible,
        carpeta: Path,
        manifest: dict[str, Any],
        numeros: Any = None,
        desfase_seed: int = 0,
    ):
        from storybook.sound.generator import GeneradorSonido

        etapa = GeneradorSonido(
            self.cfg.sound, self.cfg.consistency.base_seed + desfase_seed, self.deps.fabrica_sonido
        ).generar(bible, carpeta, numeros)
        manifest["etapas"]["sonido"] = etapa.a_dict()
        manifest["fallbacks"] += etapa.fallbacks
        return etapa

    def _mezcla(self, etapa_voz: Any, etapa_sonido: Any, carpeta: Path, manifest: dict[str, Any]):
        from storybook.sound.mixer import mezclar_historia

        narraciones = {n.escena: n.ruta for n in etapa_voz.narraciones}
        sonidos = {s.escena: (s.ruta, s.backend) for s in etapa_sonido.sonidos}
        etapa = mezclar_historia(narraciones, sonidos, carpeta, self.cfg.mix)
        manifest["etapas"]["mezcla"] = etapa.a_dict()
        return etapa

    # -- API ------------------------------------------------------------------------------
    def generar(
        self,
        idea: str,
        genero: str,
        genero_otro: str | None = None,
        progreso: Progreso | None = None,
    ) -> HistoriaGuardada:
        """Genera una historia completa. ``ValueError`` si la entrada no es válida;
        ``PipelineError`` si no se pudo escribir la historia."""
        solicitud = validar_entrada(idea, genero, genero_otro)
        carpeta = crear_carpeta_run(solicitud.idea, self.raiz)
        manifest = self._manifest_base(carpeta, solicitud)
        guardar_json(carpeta / ARCHIVO_MANIFEST, manifest)
        inicio_total = time.perf_counter()
        etapas = {clave: (mensaje, ini, fin) for clave, mensaje, ini, fin in ETAPAS}

        def correr(clave: str, funcion: Callable[[], Any]) -> Any:
            mensaje, ini, fin = etapas[clave]
            self._avisar(progreso, clave, ini, mensaje)
            inicio = time.perf_counter()
            try:
                return funcion()
            finally:
                manifest["segundos"][clave] = round(time.perf_counter() - inicio, 2)
                self._avisar(progreso, clave, fin, f"{mensaje}: listo")
                guardar_json(carpeta / ARCHIVO_MANIFEST, manifest)

        try:
            escribir = self.deps.escribir or escribir_con_ollama
            bible, info_texto = correr("texto", lambda: escribir(solicitud, self.cfg.llm))
            bible = bible.model_copy(update={"genero": solicitud.genero_efectivo})
            manifest["etapas"]["texto"] = info_texto
            manifest["titulo"] = bible.titulo
            guardar_bible(carpeta, bible)

            bible = correr("imagen", lambda: self._imagenes(bible, carpeta, manifest))
            guardar_bible(carpeta, bible)  # con las seeds asignadas
            etapa_voz = correr("voz", lambda: self._voz(bible, carpeta, manifest))
            etapa_sonido = correr("sonido", lambda: self._sonido(bible, carpeta, manifest))
            if etapa_voz is not None:
                correr("mezcla", lambda: self._mezcla(etapa_voz, etapa_sonido, carpeta, manifest))
            manifest["estado"] = "completa_con_fallbacks" if manifest["fallbacks"] else "completa"
        except PipelineError as exc:
            manifest.update(estado="fallida", error=str(exc))
            raise
        except Exception as exc:
            manifest.update(estado="fallida", error=f"{type(exc).__name__}: {exc}")
            logger.exception("pipeline_fallido", extra=kv(run_id=carpeta.name))
            raise PipelineError(f"La generación falló: {type(exc).__name__}: {exc}") from exc
        finally:
            manifest["segundos"]["total"] = round(time.perf_counter() - inicio_total, 2)
            guardar_json(carpeta / ARCHIVO_MANIFEST, manifest)
        logger.info(
            "historia_generada",
            extra=kv(run_id=carpeta.name, segundos=manifest["segundos"], estado=manifest["estado"]),
        )
        return cargar_historia(carpeta)

    def regenerar_escena(
        self, carpeta: Path, numero: int, progreso: Progreso | None = None
    ) -> HistoriaGuardada:
        """Nueva ilustración y nuevo ambiente para la escena ``numero`` (el texto y la voz
        no cambian). La seed de la imagen cambia y queda registrada en el manifest."""
        if not 1 <= numero <= NUM_ESCENAS:
            raise ValueError(f"La escena debe estar entre 1 y {NUM_ESCENAS}")
        bible = cargar_bible(carpeta)
        manifest = cargar_manifest(carpeta)
        regeneraciones = manifest.setdefault("regeneraciones", [])
        vez = 1 + sum(1 for r in regeneraciones if r.get("escena") == numero)
        escena = bible.escena(numero)
        base = (
            escena.seed_imagen if escena.seed_imagen is not None else self.cfg.consistency.base_seed
        )
        nueva_seed = (base + PASO_SEED_REGENERAR * vez) % SEED_MAX
        escenas = [
            e.model_copy(update={"seed_imagen": nueva_seed}) if e.numero == numero else e
            for e in bible.escenas
        ]
        bible = bible.model_copy(update={"escenas": escenas})
        inicio = time.perf_counter()

        self._avisar(progreso, "imagen", 0.1, f"Nueva ilustración de la escena {numero}")
        from storybook.image.generator import GeneradorImagenes

        etapa_img = GeneradorImagenes(
            self.cfg.image, self.cfg.consistency, self.deps.backend_imagen
        ).generar(bible, carpeta, numeros=[numero])
        guardar_bible(carpeta, bible)

        self._avisar(progreso, "sonido", 0.6, f"Nuevo ambiente de la escena {numero}")
        temporal: dict[str, Any] = {"etapas": {}, "fallbacks": [], "errores": []}
        etapa_sonido = self._sonido(bible, carpeta, temporal, [numero], desfase_seed=vez * 101)
        voz = carpeta / f"voice_{numero}.wav"
        if voz.is_file():
            from storybook.sound.mixer import mezclar_historia

            self._avisar(progreso, "mezcla", 0.9, f"Mezclando la escena {numero}")
            sonido = etapa_sonido.por_escena(numero)
            mezclar_historia(
                {numero: voz}, {numero: (sonido.ruta, sonido.backend)}, carpeta, self.cfg.mix
            )
        regeneraciones.append(
            {
                "escena": numero,
                "fecha": datetime.now().isoformat(timespec="seconds"),
                "seed_imagen": nueva_seed,
                "imagen": etapa_img.a_dict(),
                "sonido_backend": etapa_sonido.por_escena(numero).backend,
                "fallbacks": etapa_img.fallbacks + temporal["fallbacks"],
                "segundos": round(time.perf_counter() - inicio, 2),
            }
        )
        guardar_json(carpeta / ARCHIVO_MANIFEST, manifest)
        self._avisar(progreso, "listo", 1.0, f"Escena {numero} regenerada")
        return cargar_historia(carpeta)
