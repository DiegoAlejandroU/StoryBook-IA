"""Generación por escenas (12 nov): cada escena se avisa apenas está lista, sin GPU ni Ollama."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from storybook import config
from storybook.mock import LLMSimulado, VozSimulada, dependencias_simuladas
from storybook.pipeline import Pipeline, PipelineError
from storybook.progresivo import ARCHIVO_PARCIAL, EscenaLista, PlanListo, bible_parcial
from storybook.schemas import PlanHistoria, StoryBible
from storybook.sound.generator import (
    DiffusersSonidoBackend,
    GeneradorSonido,
    ProceduralBackend,
)
from storybook.story.llm_client import LLMResponseError
from storybook.story.por_escenas import FALLBACK_NUM_GPU_AUTO, EscritorPorEscenas
from tests.fake_llm import FakeLLM
from tests.test_image_generator import FakeBackend
from tests.test_tts import FakeTTS

IDEA = "Un faro abandonado que se enciende solo cada noche"


@pytest.fixture
def cfg() -> config.AppConfig:
    base = config.load_config("rapido")
    return base.model_copy(update={"sound": base.sound.model_copy(update={"duration_s": 2.0})})


class ContarCargas(FakeBackend):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cargas: list[Any] = []

    def cargar(self, cfg: config.ImageConfig) -> Any:
        self.cargas.append(cfg)
        return super().cargar(cfg)


class LLMQueFalla(LLMSimulado):
    """Escribe bien hasta la escena ``falla_en`` y ahí se rinde."""

    def __init__(self, falla_en: int) -> None:
        super().__init__()
        self.falla_en = falla_en

    def generar_validado(self, *, modelo_salida: type[Any], **kwargs: Any) -> Any:
        if modelo_salida is not PlanHistoria and self.escritas + 1 == self.falla_en:
            raise RuntimeError("salida inválida tras 4 intentos")
        return super().generar_validado(modelo_salida=modelo_salida, **kwargs)


def _pipeline(cfg: config.AppConfig, raiz: Path, **cambios: Any) -> Pipeline:
    deps = dependencias_simuladas(0.0)
    for clave, valor in cambios.items():
        setattr(deps, clave, valor)
    return Pipeline(cfg, deps, raiz)


def test_cada_escena_se_avisa_apenas_esta_lista(cfg: config.AppConfig, tmp_path: Path) -> None:
    eventos: list[Any] = []
    llm = LLMSimulado()
    imagen = ContarCargas()

    def al_estar_lista(lista: EscenaLista) -> None:
        # Cuando llega el aviso, la escena ya tiene todos sus archivos y la siguiente no existe.
        assert lista.archivos.completa
        assert not (lista.carpeta / f"scene_{lista.numero + 1}.png").exists()
        assert llm.escritas == lista.numero  # el LLM aún no escribió la siguiente
        eventos.append(lista)

    historia = _pipeline(cfg, tmp_path, llm=llm, backend_imagen=imagen).generar_por_escenas(
        IDEA, "misterio", al_estar_lista=al_estar_lista, al_planificar=eventos.append
    )
    plan, *listas = eventos
    assert isinstance(plan, PlanListo) and plan.titulo == historia.titulo
    assert len(plan.resumenes) == 5
    assert [e.numero for e in listas] == [1, 2, 3, 4, 5]
    assert [e.lista_en_s for e in listas] == sorted(e.lista_en_s for e in listas)
    assert listas[0].detalles["imagen"]["escena"] == 1 and "sonido" in listas[0].detalles
    assert listas[2].escena.texto_narrativo == historia.bible.escena(3).texto_narrativo

    # El modelo de imagen se carga una sola vez y con offload (la GPU queda para el LLM).
    assert len(imagen.cargas) == 1 and imagen.cargas[0].cpu_offload is True
    assert llm.descargas >= 5  # el LLM sale de la VRAM después de cada escena
    assert historia.completa and historia.bible.genero == "misterio"
    assert not (historia.carpeta / ARCHIVO_PARCIAL).exists()

    manifest = json.loads((historia.carpeta / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["modo"] == "por_escenas" and manifest["estado"] == "completa"
    assert [x["escena"] for x in manifest["escenas_listas"]] == [1, 2, 3, 4, 5]
    assert manifest["segundos"]["primera_escena"] == manifest["escenas_listas"][0]["lista_en_s"]
    assert manifest["etapas"]["texto"]["estrategia"] == "por_escenas"
    assert manifest["etapas"]["texto"]["auditoria"] is None
    assert len(manifest["etapas"]["texto"]["llamadas"]) == 6  # plan + 5 escenas
    assert len(manifest["etapas"]["imagen"]["imagenes"]) == 5
    assert len(manifest["etapas"]["voz"]["narraciones"]) == 5
    assert len(manifest["etapas"]["sonido"]["sonidos"]) == 5
    assert len(manifest["etapas"]["mezcla"]["mezclas"]) == 5


def test_mismas_seeds_que_la_generacion_completa(cfg: config.AppConfig, tmp_path: Path) -> None:
    completa = _pipeline(cfg, tmp_path / "a").generar(IDEA, "misterio")
    por_escenas = _pipeline(cfg, tmp_path / "b").generar_por_escenas(IDEA, "misterio")
    assert [e.seed_imagen for e in completa.bible.escenas] == [
        e.seed_imagen for e in por_escenas.bible.escenas
    ]
    assert [p.seed for p in completa.bible.personajes] == [
        p.seed for p in por_escenas.bible.personajes
    ]


def test_si_el_llm_falla_quedan_las_escenas_ya_listas(
    cfg: config.AppConfig, tmp_path: Path
) -> None:
    listas: list[EscenaLista] = []
    pipeline = _pipeline(cfg, tmp_path, llm=LLMQueFalla(falla_en=3))
    with pytest.raises(PipelineError, match="después de la escena 2"):
        pipeline.generar_por_escenas(IDEA, "misterio", al_estar_lista=listas.append)
    assert [e.numero for e in listas] == [1, 2]
    carpeta = listas[0].carpeta
    manifest = json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["estado"] == "incompleta" and len(manifest["escenas_listas"]) == 2
    assert (carpeta / ARCHIVO_PARCIAL).is_file()  # el texto escrito no se pierde
    assert not (carpeta / "story.json").exists()  # no aparece como historia terminada


def test_sin_modelo_de_imagen_siguen_las_escenas_con_respaldo(
    cfg: config.AppConfig, tmp_path: Path
) -> None:
    historia = _pipeline(
        cfg, tmp_path, backend_imagen=FakeBackend(fallar_carga=True)
    ).generar_por_escenas(IDEA, "misterio")
    assert historia.completa
    manifest = historia.manifest
    assert "imagen:respaldo:todas" in manifest["fallbacks"]
    assert manifest["estado"] == "completa_con_fallbacks"


def test_si_la_voz_no_carga_no_se_reintenta_en_cada_escena(
    cfg: config.AppConfig, tmp_path: Path
) -> None:
    voz = FakeTTS(fallar_carga=True)
    listas: list[EscenaLista] = []
    historia = _pipeline(cfg, tmp_path, backend_voz=voz).generar_por_escenas(
        IDEA, "misterio", al_estar_lista=listas.append
    )
    assert len(listas) == 5 and all(e.archivos.voz is None for e in listas)
    assert all(e.archivos.ambiente is not None for e in listas)  # el ambiente sí está
    assert historia.manifest["fallbacks"].count("voz:sin_narracion") == 1
    assert "mezcla" not in historia.manifest["etapas"]


def test_progreso_avanza_siempre(cfg: config.AppConfig, tmp_path: Path) -> None:
    avances: list[float] = []
    _pipeline(cfg, tmp_path).generar_por_escenas(
        IDEA, "terror", progreso=lambda _e, avance, _m: avances.append(avance)
    )
    assert avances == sorted(avances) and avances[-1] == 1.0


def test_entrada_invalida_no_crea_carpeta(cfg: config.AppConfig, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _pipeline(cfg, tmp_path).generar_por_escenas("corta", "misterio")
    assert not any(tmp_path.iterdir())


def test_bible_parcial_solo_con_las_escenas_escritas(bible_dict: dict[str, Any]) -> None:
    bible = StoryBible.model_validate(bible_dict)
    plan = PlanHistoria.model_validate(_plan_y_escenas(bible_dict)[0])
    parcial = bible_parcial(plan, [bible.escena(1), bible.escena(2)])
    assert [e.numero for e in parcial.escenas] == [1, 2]
    assert parcial.escena(2).texto_narrativo == bible.escena(2).texto_narrativo
    assert parcial.protagonista().id == bible.protagonista().id
    assert parcial.estilo_visual == bible.estilo_visual
    # Las etapas de imagen le asignan seeds aunque falten escenas.
    assert all(e.seed_imagen is not None for e in parcial.con_seeds(1234).escenas)


# ---------------------------------------------------------------------------------------
# Escritor por escenas
# ---------------------------------------------------------------------------------------
def _plan_y_escenas(bible_dict: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = {
        **{k: bible_dict[k] for k in ("titulo", "genero", "tono", "estilo_visual", "escenario")},
        "personajes": bible_dict["personajes"],
        "plan_escenas": [
            {
                "numero": e["numero"],
                "fase": e["fase"],
                "resumen": e["resumen"],
                "personajes_presentes": e["personajes_presentes"],
            }
            for e in bible_dict["escenas"]
        ],
    }
    return plan, bible_dict["escenas"]


def test_escritor_reintenta_con_capas_automaticas(bible_dict: dict[str, Any]) -> None:
    """Desde la escena 2 hay menos VRAM libre: si Ollama falla con 99 capas, modo automático."""
    plan_d, escenas = _plan_y_escenas(bible_dict)
    llm = FakeLLM().encolar("PlanHistoria", plan_d)
    llm.encolar("Escena", LLMResponseError("cudaMalloc failed: out of memory"), escenas[0])
    cfg = config.load_config("rapido").llm
    assert cfg.num_gpu == 99
    from storybook.schemas import validar_entrada

    solicitud = validar_entrada(IDEA, "misterio")
    with EscritorPorEscenas(cfg, llm) as escritor:
        plan = escritor.planificar(solicitud)
        escena = escritor.escena(plan, 1, [], solicitud.genero)
    assert escena.numero == 1
    num_gpu = [c["opciones_extra"].get("num_gpu") for c in llm.llamadas]
    assert num_gpu == [99, 99, None]
    info = escritor.info()
    assert info["fallbacks"] == [FALLBACK_NUM_GPU_AUTO] and info["num_gpu"] is None
    assert [r["etapa"] for r in info["llamadas"]] == ["plan", "escena_1"]
    assert llm.descargados  # al cerrar se libera la VRAM


def test_escritor_pasa_el_canon_de_las_escenas_previas(bible_dict: dict[str, Any]) -> None:
    plan_d, escenas = _plan_y_escenas(bible_dict)
    escenas[0] = {**escenas[0], "hechos_nuevos": ["La lámpara del faro es azul."]}
    llm = FakeLLM().encolar("PlanHistoria", plan_d).encolar("Escena", escenas[0], escenas[1])
    from storybook.schemas import Escena, validar_entrada

    solicitud = validar_entrada(IDEA, "misterio")
    with EscritorPorEscenas(config.load_config("rapido").llm, llm) as escritor:
        plan = escritor.planificar(solicitud)
        primera = escritor.escena(plan, 1, [], solicitud.genero)
        escritor.escena(plan, 2, [primera], solicitud.genero)
    assert isinstance(primera, Escena)
    mensaje = llm.llamadas_de(Escena)[1]["messages"][-1]["content"]
    assert "La lámpara del faro es azul." in mensaje and "Escena 1:" in mensaje


# ---------------------------------------------------------------------------------------
# Sesiones de sonido
# ---------------------------------------------------------------------------------------
class SonidoContado(ProceduralBackend):
    def __init__(self, nombre: str, registro: list[str], oom: bool = False) -> None:
        super().__init__()
        self.nombre = nombre
        self.registro = registro
        self.oom = oom

    def cargar(self) -> None:
        self.registro.append(f"carga:{self.nombre}")

    def generar(self, escena: Any, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
        if self.oom:
            raise MemoryError("CUDA out of memory")
        return super().generar(escena, duracion_s, seed)

    def es_oom(self, exc: BaseException) -> bool:
        return isinstance(exc, MemoryError)

    def liberar(self) -> None:
        self.registro.append(f"libera:{self.nombre}")


def test_sesion_de_sonido_carga_cada_backend_una_vez(
    tmp_path: Path, bible_dict: dict[str, Any]
) -> None:
    bible = StoryBible.model_validate(bible_dict)
    registro: list[str] = []
    pedidos: list[str] = []
    cfg = config.load_config("rapido").sound.model_copy(
        update={"backends": ["sa3", "audioldm", "procedural"], "duration_s": 1.0}
    )

    def fabrica(nombre: str) -> Any:
        pedidos.append(nombre)
        if nombre == "sa3":
            raise FileNotFoundError("'stabilityai/stable-audio-3-small-sfx' no está descargado")
        return SonidoContado(nombre, registro)

    with GeneradorSonido(cfg, 1234, fabrica).sesion(tmp_path) as sesion:
        for numero in (1, 2, 3):
            sesion.escena(bible.escena(numero))
            sesion.estacionar()
    assert {s.escena: s.backend for s in sesion.etapa.sonidos} == {
        1: "audioldm",
        2: "audioldm",
        3: "audioldm",
    }
    assert pedidos == ["sa3", "audioldm"]  # sa3 no se reintenta en cada escena
    assert registro == ["carga:audioldm", "libera:audioldm"]
    assert sesion.etapa.backends["sa3"]["estado"] == "no_disponible"
    assert sesion.etapa.fallbacks == ["sonido:sa3:no_disponible"]


def test_sesion_de_sonido_descarta_el_backend_sin_memoria(
    tmp_path: Path, bible_dict: dict[str, Any]
) -> None:
    bible = StoryBible.model_validate(bible_dict)
    registro: list[str] = []
    cfg = config.load_config("rapido").sound.model_copy(
        update={"backends": ["audioldm", "procedural"], "duration_s": 1.0}
    )
    fabrica = {
        "audioldm": lambda: SonidoContado("audioldm", registro, oom=True),
        "procedural": lambda: SonidoContado("procedural", registro),
    }
    with GeneradorSonido(cfg, 1234, lambda n: fabrica[n]()).sesion(tmp_path) as sesion:
        primero = sesion.escena(bible.escena(1))
        segundo = sesion.escena(bible.escena(2))
    assert primero.backend == segundo.backend == "procedural"
    assert registro.count("carga:audioldm") == 1  # tras el OOM no se vuelve a cargar
    assert "sonido:escena_1:audioldm_fallo" in sesion.etapa.fallbacks
    assert "sonido:escena_2:audioldm_fallo" not in sesion.etapa.fallbacks


class PipeMovible:
    def __init__(self) -> None:
        self.dispositivos: list[str] = []

    def to(self, dispositivo: str) -> PipeMovible:
        self.dispositivos.append(dispositivo)
        return self


def test_audioldm_pasa_a_ram_entre_escenas() -> None:
    backend = DiffusersSonidoBackend("audioldm", config.load_config("rapido").sound)
    pipe = PipeMovible()
    backend.pipe = pipe
    backend.estacionar()
    backend.estacionar()  # no lo mueve dos veces
    backend.activar()
    backend.activar()
    assert pipe.dispositivos == ["cpu", "cuda"]


def test_voz_simulada_y_mock_por_escenas_con_demora(tmp_path: Path) -> None:
    deps = dependencias_simuladas(0.01)
    assert isinstance(deps.llm, LLMSimulado) and deps.llm.demora_s == 0.01
    assert isinstance(deps.backend_voz, VozSimulada)
