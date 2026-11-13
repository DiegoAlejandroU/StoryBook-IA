"""Generación por escenas (pedido del docente, 12 nov): ver la escena 1 sin esperar las 5.

Con la generación completa (``Pipeline.generar``) cada modelo hace las 5 escenas y la historia
aparece al final, a los 2-3 minutos. Aquí cada escena pasa por toda la cadena antes de escribir
la siguiente, y se avisa con ``al_estar_lista`` apenas tiene texto, imagen, voz y ambiente:

    plan → [texto 1 → imagen 1 → voz 1 → ambiente 1 → mezcla 1] → aviso → [texto 2 → …] → …

En 4 GB de VRAM no caben a la vez el LLM y los modelos de imagen o sonido, así que se turnan:

* El LLM (Ollama) se descarga al terminar cada escena (``keep_alive=0``).
* El modelo de imagen se carga una sola vez, con *model CPU offload*: entre llamadas sus pesos
  quedan en RAM y la GPU libre (no se vuelve a leer del disco en cada escena). La character
  sheet y el IP-Adapter se preparan con el protagonista del plan, antes de la escena 1.
* AudioLDM también se carga una vez y pasa a RAM entre escenas (``SesionSonido.estacionar``).
* La voz (Piper) y la mezcla son de CPU.

Lo que se gana es el tiempo hasta la primera escena; el total sube un poco (el LLM se vuelve a
cargar en cada escena). No hay auditor de coherencia (ver ``storybook.story.por_escenas``).
El resultado en disco es el mismo que el de la generación completa (``story.json``,
``manifest.json`` y los archivos de cada escena), con ``modo: por_escenas`` en el manifest y
el momento en que quedó lista cada escena.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from storybook.logging_utils import get_logger, kv
from storybook.schemas import Escena, PlanHistoria, StoryBible, StoryRequest
from storybook.storage import (
    ARCHIVO_MANIFEST,
    NUM_ESCENAS,
    ArchivosEscena,
    archivos_escena,
    guardar_bible,
    guardar_json,
)

if TYPE_CHECKING:
    from storybook.pipeline import Pipeline, Progreso

logger = get_logger(__name__)

MODO: Final = "por_escenas"
ARCHIVO_PARCIAL: Final = "story_parcial.json"
# Peso de cada etapa dentro de una escena (para la barra de progreso).
PESOS_ESCENA: Final = (
    ("texto", 0.30),
    ("imagen", 0.25),
    ("voz", 0.10),
    ("sonido", 0.30),
    ("mezcla", 0.05),
)
PESO_PLAN: Final = 0.06
MENSAJES: Final = {
    "texto": "Escribiendo",
    "imagen": "Ilustrando",
    "voz": "Narrando",
    "sonido": "Creando el ambiente de",
    "mezcla": "Mezclando",
}


@dataclass(frozen=True)
class EscenaLista:
    """Lo que la interfaz necesita para mostrar una escena terminada."""

    carpeta: Path
    numero: int
    titulo: str
    genero: str
    tono: str
    escena: Escena
    archivos: ArchivosEscena
    lista_en_s: float
    detalles: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanListo:
    """Aviso previo a la escena 1: título y resumen de las 5 escenas (para la espera)."""

    carpeta: Path
    titulo: str
    genero: str
    tono: str
    resumenes: list[str]
    segundos: float
    personajes: dict[str, str] = field(default_factory=dict)  # id -> nombre


AlEstarLista = Callable[[EscenaLista], None]
AlPlanificar = Callable[[PlanListo], None]


def bible_parcial(plan: PlanHistoria, escenas: list[Escena]) -> StoryBible:
    """Bible con las escenas escritas hasta ahora (sin validar: la Bible exige 5 escenas).

    Las etapas de imagen, voz y sonido solo consultan el estilo, los personajes y la escena
    que procesan, así que les basta. La Bible final sí se valida (``StoryBible.desde_plan``).
    """
    canon = list(plan.canon_inicial)
    for escena in escenas:
        canon.extend(h for h in escena.hechos_nuevos if h not in canon)
    return StoryBible.model_construct(
        titulo=plan.titulo,
        genero=plan.genero,
        tono=plan.tono,
        idioma="es",
        estilo_visual=plan.estilo_visual,
        escenario=plan.escenario,
        personajes=[p.model_copy(deep=True) for p in plan.personajes],
        escenas=[e.model_copy(deep=True) for e in escenas],
        canon=canon,
    )


class _Avance:
    """Convierte (escena, etapa) en la fracción de la barra de progreso."""

    def __init__(self, progreso: Progreso | None, aviso: Callable[..., None]) -> None:
        self.progreso = progreso
        self.aviso = aviso

    def __call__(self, numero: int, etapa: str) -> None:
        por_escena = (1.0 - PESO_PLAN) / NUM_ESCENAS
        dentro = 0.0
        for clave, peso in PESOS_ESCENA:
            if clave == etapa:
                break
            dentro += peso
        avance = PESO_PLAN + por_escena * (numero - 1 + dentro)
        self.aviso(self.progreso, etapa, avance, f"{MENSAJES[etapa]} la escena {numero}")


class GeneracionPorEscenas:
    """Una ejecución de ``Pipeline.generar_por_escenas`` (estado de la historia en curso)."""

    def __init__(
        self,
        pipeline: Pipeline,
        solicitud: StoryRequest,
        carpeta: Path,
        manifest: dict[str, Any],
        progreso: Progreso | None,
        al_estar_lista: AlEstarLista | None,
        al_planificar: AlPlanificar | None,
    ) -> None:
        self.p = pipeline
        self.solicitud = solicitud
        self.carpeta = carpeta
        self.manifest = manifest
        self.progreso = progreso
        self.al_estar_lista = al_estar_lista
        self.al_planificar = al_planificar
        self.inicio = time.perf_counter()
        self.avance = _Avance(progreso, pipeline._avisar)
        self.segundos: dict[str, float] = {}
        self.voz_disponible = True
        self.narraciones: list[Any] = []
        self.metricas_voz: list[Any] = []
        self.backend_voz: dict[str, Any] = {}
        self.mezclas: list[Any] = []
        self.metricas_mezcla: list[Any] = []
        self.listas: list[dict[str, Any]] = []

    # -- utilidades -------------------------------------------------------------------------
    def _transcurrido(self) -> float:
        return round(time.perf_counter() - self.inicio, 2)

    def _medir(self, clave: str, funcion: Callable[[], Any]) -> Any:
        inicio = time.perf_counter()
        try:
            return funcion()
        finally:
            self.segundos[clave] = round(
                self.segundos.get(clave, 0.0) + time.perf_counter() - inicio, 2
            )

    def _guardar(self) -> None:
        self.manifest["segundos"].update(self.segundos)
        guardar_json(self.carpeta / ARCHIVO_MANIFEST, self.manifest)

    # -- ejecución --------------------------------------------------------------------------
    def ejecutar(self) -> StoryBible:
        from storybook.image.generator import GeneradorImagenes
        from storybook.sound.generator import GeneradorSonido
        from storybook.story.por_escenas import EscritorPorEscenas

        cfg = self.p.cfg
        # Imagen con offload: entre escenas los pesos quedan en RAM y el LLM tiene la GPU.
        cfg_imagen = cfg.image.model_copy(update={"cpu_offload": True})
        generador_img = GeneradorImagenes(cfg_imagen, cfg.consistency, self.p.deps.backend_imagen)
        generador_snd = GeneradorSonido(
            cfg.sound, cfg.consistency.base_seed, self.p.deps.fabrica_sonido
        )
        escenas: list[Escena] = []
        sesion_img: Any = None
        # Al salir se cierra en orden inverso: imagen, sonido y por último el LLM.
        with ExitStack() as pila:
            escritor = pila.enter_context(EscritorPorEscenas(cfg.llm, self.p.deps.llm))
            sesion_snd = pila.enter_context(generador_snd.sesion(self.carpeta))
            try:
                self.p._avisar(self.progreso, "texto", 0.0, "Planeando la historia (LLM local)")
                plan = self._medir("texto", lambda: escritor.planificar(self.solicitud))
                self._registrar_texto(escritor)
                self._plan_listo(plan)
                for numero in range(1, NUM_ESCENAS + 1):
                    if numero > 1:  # la GPU para el LLM: imagen y sonido quedan en RAM
                        if sesion_img is not None:
                            sesion_img.estacionar()
                        sesion_snd.estacionar()
                    self.avance(numero, "texto")
                    escena = self._medir(
                        "texto",
                        lambda n=numero: escritor.escena(plan, n, escenas, self.solicitud.genero),
                    )
                    escritor.liberar_vram()
                    escenas.append(escena)
                    self._registrar_texto(escritor)
                    parcial = bible_parcial(plan, escenas)
                    if numero == 1:
                        sesion_img = self._abrir_imagen(pila, generador_img, parcial)
                    self._escena(numero, parcial, sesion_img, sesion_snd, generador_img)
            finally:
                if sesion_img is not None:
                    self.manifest["etapas"]["imagen"] = sesion_img.etapa.a_dict()
                self.manifest["etapas"]["sonido"] = sesion_snd.etapa.a_dict()
                self._registrar_texto(escritor)
        return self._bible_final(plan, escenas, sesion_img, generador_img)

    def _registrar_texto(self, escritor: Any) -> None:
        self.manifest["etapas"]["texto"] = escritor.info()
        self._agregar_fallbacks(escritor.fallbacks)

    def _agregar_fallbacks(self, codigos: list[str]) -> None:
        for codigo in codigos:
            if codigo not in self.manifest["fallbacks"]:
                self.manifest["fallbacks"].append(codigo)

    def _plan_listo(self, plan: PlanHistoria) -> None:
        self.manifest["titulo"] = plan.titulo
        (self.carpeta / ARCHIVO_PARCIAL).write_text(
            bible_parcial(plan, []).model_dump_json(indent=2), encoding="utf-8"
        )
        self._guardar()
        if self.al_planificar is not None:
            self.al_planificar(
                PlanListo(
                    carpeta=self.carpeta,
                    titulo=plan.titulo,
                    genero=self.solicitud.genero_efectivo,
                    tono=plan.tono,
                    resumenes=[e.resumen for e in plan.plan_escenas],
                    segundos=self._transcurrido(),
                    personajes={p.id: p.nombre for p in plan.personajes},
                )
            )

    def _abrir_imagen(self, pila: ExitStack, generador: Any, parcial: StoryBible) -> Any:
        """Carga el modelo, la character sheet y el IP-Adapter; ``None`` si no carga."""
        from storybook.image.generator import FALLBACK_RESPALDO, ImageModelError

        avance = PESO_PLAN + (1.0 - PESO_PLAN) / NUM_ESCENAS * PESOS_ESCENA[0][1]
        self.p._avisar(
            self.progreso, "imagen", avance, "Preparando el ilustrador y el personaje de referencia"
        )
        sesion = generador.sesion(parcial, self.carpeta)
        try:
            return self._medir("imagen", lambda: pila.enter_context(sesion))
        except ImageModelError as exc:
            self.manifest["fallbacks"].append(f"{FALLBACK_RESPALDO}:todas")
            self.manifest["errores"].append(f"imagen: {exc}")
            self.manifest["etapas"]["imagen"] = {"error": str(exc)}
            return None

    def _escena(
        self,
        numero: int,
        parcial: StoryBible,
        sesion_img: Any,
        sesion_snd: Any,
        generador_img: Any,
    ) -> None:
        from storybook.image.generator import imagen_respaldo, nombre_archivo_escena

        cfg = self.p.cfg
        detalles: dict[str, Any] = {}
        self.avance(numero, "imagen")
        if sesion_img is not None:
            resultado = self._medir("imagen", lambda: sesion_img.escena(parcial, numero))
            detalles["imagen"] = resultado.a_dict()
            parcial = sesion_img.etapa.bible
            self.manifest["etapas"]["imagen"] = sesion_img.etapa.a_dict()
            self._agregar_fallbacks(sesion_img.etapa.fallbacks)
        else:
            imagen_respaldo(cfg.image.width, cfg.image.height, numero).save(
                self.carpeta / nombre_archivo_escena(numero)
            )
            parcial = generador_img.asegurar_seeds(parcial)

        voz = None
        if self.voz_disponible:
            self.avance(numero, "voz")
            temporal: dict[str, Any] = {"etapas": {}, "fallbacks": [], "errores": []}
            etapa_voz = self._medir(
                "voz", lambda: self.p._voz(parcial, self.carpeta, temporal, [numero])
            )
            if etapa_voz is None:
                self.voz_disponible = False  # Piper no cargó: tampoco lo hará en la siguiente
                self._agregar_fallbacks(temporal["fallbacks"])
                self.manifest["errores"] += temporal["errores"]
                self.manifest["etapas"]["voz"] = temporal["etapas"]["voz"]
            else:
                voz = etapa_voz.narraciones[0]
                self.narraciones.append(voz)
                self.metricas_voz += etapa_voz.metricas
                self.backend_voz = etapa_voz.backend
                detalles["voz"] = voz.a_dict()
                self.manifest["etapas"]["voz"] = {
                    "backend": self.backend_voz,
                    "duracion_total_s": round(sum(n.duracion_s for n in self.narraciones), 3),
                    "narraciones": [n.a_dict() for n in self.narraciones],
                    "metricas": [m.as_dict() for m in self.metricas_voz],
                }

        self.avance(numero, "sonido")
        sonido = self._medir("sonido", lambda: sesion_snd.escena(parcial.escena(numero)))
        detalles["sonido"] = sonido.a_dict()
        self.manifest["etapas"]["sonido"] = sesion_snd.etapa.a_dict()
        self._agregar_fallbacks(sesion_snd.etapa.fallbacks)

        if voz is not None:
            from storybook.sound.mixer import mezclar_historia

            self.avance(numero, "mezcla")
            mezcla = self._medir(
                "mezcla",
                lambda: mezclar_historia(
                    {numero: voz.ruta},
                    {numero: (sonido.ruta, sonido.backend)},
                    self.carpeta,
                    cfg.mix,
                ),
            )
            self.mezclas += mezcla.mezclas
            detalles["mezcla"] = mezcla.mezclas[0].a_dict()
            self.metricas_mezcla += mezcla.metricas
            self.manifest["etapas"]["mezcla"] = {
                "mezclas": [m.a_dict() for m in self.mezclas],
                "metricas": [m.as_dict() for m in self.metricas_mezcla],
            }

        lista_en = self._transcurrido()
        self.listas.append({"escena": numero, "lista_en_s": lista_en})
        self.manifest["escenas_listas"] = self.listas
        self.manifest["segundos"]["primera_escena"] = self.listas[0]["lista_en_s"]
        (self.carpeta / ARCHIVO_PARCIAL).write_text(parcial.model_dump_json(indent=2), "utf-8")
        self._guardar()
        logger.info("escena_lista", extra=kv(escena=numero, segundos=lista_en))
        if self.al_estar_lista is not None:
            self.al_estar_lista(
                EscenaLista(
                    carpeta=self.carpeta,
                    numero=numero,
                    titulo=parcial.titulo,
                    genero=self.solicitud.genero_efectivo,
                    tono=parcial.tono,
                    escena=parcial.escena(numero),
                    archivos=archivos_escena(self.carpeta, numero),
                    lista_en_s=lista_en,
                    detalles=detalles,
                )
            )

    def _bible_final(
        self, plan: PlanHistoria, escenas: list[Escena], sesion_img: Any, generador_img: Any
    ) -> StoryBible:
        """La Bible validada, con las seeds que de verdad se usaron en cada ilustración."""
        bible = StoryBible.desde_plan(plan, escenas)
        bible = bible.model_copy(update={"genero": self.solicitud.genero_efectivo})
        bible = generador_img.asegurar_seeds(bible)
        if sesion_img is not None:
            usada = sesion_img.etapa.bible
            seeds_personajes = {p.id: p.seed for p in usada.personajes}
            seeds_escenas = {r.escena: r.seed for r in sesion_img.etapa.imagenes}
            bible = bible.model_copy(
                update={
                    "personajes": [
                        p.model_copy(update={"seed": seeds_personajes.get(p.id, p.seed)})
                        for p in bible.personajes
                    ],
                    "escenas": [
                        e.model_copy(
                            update={"seed_imagen": seeds_escenas.get(e.numero, e.seed_imagen)}
                        )
                        for e in bible.escenas
                    ],
                }
            )
        guardar_bible(self.carpeta, bible)
        (self.carpeta / ARCHIVO_PARCIAL).unlink(missing_ok=True)
        return bible


def manifest_por_escenas(manifest: dict[str, Any]) -> dict[str, Any]:
    """Campos propios del modo por escenas en el manifest base."""
    manifest.update(
        modo=MODO,
        escenas_listas=[],
        inicio=datetime.now().isoformat(timespec="seconds"),
    )
    return manifest
