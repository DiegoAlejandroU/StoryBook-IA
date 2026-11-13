"""Generación en segundo plano y vista de libro (interfaz del 12 nov), sin Streamlit."""

from __future__ import annotations

import functools
import threading
from pathlib import Path
from typing import Any

import pytest

from storybook import config, ui_logica
from storybook.generacion_en_curso import MENSAJE_OCUPADO, GeneracionEnCurso
from storybook.mock import dependencias_simuladas
from storybook.pipeline import Pipeline, PipelineError
from storybook.storage import cargar_historia

IDEA = "Un faro abandonado que se enciende solo cada noche"


def _cfg() -> config.AppConfig:
    base = config.load_config("rapido")
    return base.model_copy(update={"sound": base.sound.model_copy(update={"duration_s": 1.0})})


def _generacion(tmp_path: Path, **kwargs: Any) -> GeneracionEnCurso:
    pipeline = Pipeline(_cfg(), dependencias_simuladas(0.0), tmp_path)
    generar = functools.partial(pipeline.generar_por_escenas, IDEA, "misterio", None)
    return GeneracionEnCurso(generar, perfil="rapido", idea=IDEA, **kwargs)


def test_las_escenas_llegan_a_la_instantanea(tmp_path: Path) -> None:
    generacion = _generacion(tmp_path, candado=threading.Lock()).iniciar()
    generacion.esperar(60)
    final = generacion.instantanea()
    assert final.terminada and final.error is None and final.avance == 1.0
    assert sorted(final.listas) == [1, 2, 3, 4, 5] and final.en_curso is None
    assert final.plan is not None and final.carpeta == final.listas[1].carpeta
    assert final.plan.personajes  # id -> nombre, para el panel técnico


def test_en_curso_es_la_siguiente_escena() -> None:
    from storybook.generacion_en_curso import Instantanea

    assert Instantanea(activa=True).en_curso == 1
    lista: Any = object()
    assert Instantanea(activa=True, listas={1: lista, 2: lista}).en_curso == 3
    assert Instantanea(activa=True, terminada=True).en_curso is None


def test_no_hay_dos_generaciones_a_la_vez(tmp_path: Path) -> None:
    candado = threading.Lock()
    candado.acquire()
    generacion = _generacion(tmp_path, candado=candado).iniciar()
    generacion.esperar(10)
    assert generacion.instantanea().error == MENSAJE_OCUPADO
    assert not any(tmp_path.iterdir())  # no empezó
    candado.release()


def test_un_error_queda_en_la_instantanea_y_libera_la_gpu(tmp_path: Path) -> None:
    candado = threading.Lock()

    def falla(**_: Any) -> None:
        raise PipelineError("Ollama no responde en http://localhost:11434.")

    generacion = GeneracionEnCurso(falla, perfil="rapido", idea=IDEA, candado=candado).iniciar()
    generacion.esperar(10)
    assert generacion.instantanea().error == "Ollama no responde en http://localhost:11434."
    assert not candado.locked()


# ---------------------------------------------------------------------------------------
# Vista de libro
# ---------------------------------------------------------------------------------------
@pytest.fixture
def historia(tmp_path: Path) -> Any:
    pipeline = Pipeline(_cfg(), dependencias_simuladas(0.0), tmp_path)
    return pipeline.generar_por_escenas(IDEA, "misterio")


def test_vista_de_una_historia_guardada(historia: Any) -> None:
    vista = ui_logica.vista_de_historia(historia)
    assert sorted(vista.paginas) == [1, 2, 3, 4, 5] and vista.terminada
    assert all(vista.estado(n) == "lista" and vista.navegable(n) for n in range(1, 6))
    pagina = vista.paginas[2]
    assert pagina.texto == historia.bible.escena(2).texto_narrativo
    assert pagina.lista_en_s is not None  # generada por escenas: momento en que quedó lista
    assert {"imagen", "voz", "sonido", "mezcla"} <= set(pagina.detalles)
    assert (
        vista.personajes[historia.bible.protagonista().id] == historia.bible.protagonista().nombre
    )
    filas = dict(ui_logica.filas_historia(vista))
    assert filas["Imágenes"] == "DreamShaper 8 (SD 1.5), 6 pasos"
    assert "Primera escena" in filas and "Historia completa" in filas


def test_vista_en_vivo_con_escenas_pendientes(tmp_path: Path) -> None:
    generacion = _generacion(tmp_path, candado=threading.Lock()).iniciar()
    generacion.esperar(60)
    final = generacion.instantanea()
    parcial = type(final)(
        activa=True, plan=final.plan, listas={1: final.listas[1]}, perfil="rapido"
    )
    vista = ui_logica.vista_en_vivo(parcial, _cfg().model_dump(mode="json"))
    assert vista.titulo == final.plan.titulo and len(vista.resumenes) == 5
    assert [vista.estado(n) for n in range(1, 6)] == [
        "lista",
        "en_curso",
        "pendiente",
        "pendiente",
        "pendiente",
    ]
    assert vista.navegable(2) and not vista.navegable(3)
    assert vista.paginas[1].lista_en_s == final.listas[1].lista_en_s


def test_filas_de_la_escena_para_el_panel() -> None:
    detalles = {
        "imagen": {
            "seed": 42,
            "segundos": 3.25,
            "ip_escala": 0.2,
            "prompt": {"foco": "luna_perez", "prompt": "a lighthouse at night"},
        },
        "voz": {"duracion_s": 36.7},
        "sonido": {"backend": "audioldm", "detalle": {"prompt_efectivo": "waves, high quality"}},
        "mezcla": {"lufs_voz": -18.0, "ambiente_bajo_voz_db": 12.0},
        "lista_en_s": 52.4,
    }
    filas = dict(ui_logica.filas_escena(detalles, {"luna_perez": "Luna Pérez"}))
    assert filas["Personaje en foco"] == "Luna Pérez"
    assert filas["Referencia del protagonista"] == "IP-Adapter 0,20"
    assert filas["Tiempo de la imagen"] == "3,2 s"
    assert filas["Ambiente"] == "AudioLDM"
    assert filas["Mezcla"] == "voz a -18,0 LUFS, ambiente 12 dB por debajo"
    assert filas["Lista a los"] == "52 s"
    sin_ip = dict(ui_logica.filas_escena({"imagen": {"ip_escala": 0.0}}, {}))
    assert sin_ip["Referencia del protagonista"] == "no se aplica en esta escena"
    assert ui_logica.prompts_escena(detalles) == {
        "Ilustración": "a lighthouse at night",
        "Ambiente": "waves, high quality",
    }


def test_las_regeneraciones_mandan_en_los_detalles(historia: Any) -> None:
    manifest = dict(historia.manifest)
    manifest["regeneraciones"] = [
        {
            "escena": 2,
            "imagen": {"imagenes": [{"escena": 2, "seed": 777, "prompt": {}}]},
            "sonido_backend": "procedural",
        }
    ]
    detalles = ui_logica.detalles_desde_manifest(manifest, 2)
    assert detalles["imagen"]["seed"] == 777 and detalles["sonido"]["backend"] == "procedural"
    assert ui_logica.detalles_desde_manifest(manifest, 3)["imagen"]["seed"] != 777


def test_subtitulo_y_fases() -> None:
    vista = ui_logica.VistaLibro(
        titulo="T", genero="misterio", tono="inquietante", perfil="rapido", paginas={}
    )
    assert ui_logica.subtitulo(vista) == "Misterio, inquietante"
    assert ui_logica.fase_legible(ui_logica.FASE_POR_ESCENA[4]) == "Clímax"
    assert vista.estado(1) == "pendiente" and not vista.navegable(1)


def test_historia_guardada_carga_igual(historia: Any) -> None:
    assert cargar_historia(historia.carpeta).completa
