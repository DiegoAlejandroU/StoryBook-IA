"""Pipeline completo con dependencias simuladas (tarea 5.1): 5 escenas con todos sus archivos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import soundfile as sf

from storybook import config
from storybook.mock import VozSimulada, dependencias_simuladas
from storybook.pipeline import Dependencias, Pipeline, PipelineError
from storybook.schemas import InputValidationError
from storybook.storage import (
    TIPO_MANIFEST,
    archivos_escena,
    cargar_historia,
    listar_historias,
    nuevo_run_id,
    slug,
)

IDEA = "Un faro abandonado que se enciende solo cada noche"


@pytest.fixture
def cfg() -> config.AppConfig:
    base = config.load_config("rapido")
    return base.model_copy(update={"sound": base.sound.model_copy(update={"duration_s": 2.0})})


def _pipeline(cfg: config.AppConfig, raiz: Path, **cambios: Any) -> Pipeline:
    deps = dependencias_simuladas()
    for clave, valor in cambios.items():
        setattr(deps, clave, valor)
    return Pipeline(cfg, deps, raiz)


def test_historia_completa_con_todos_los_archivos(cfg: config.AppConfig, tmp_path: Path) -> None:
    avances: list[tuple[str, float]] = []
    historia = _pipeline(cfg, tmp_path).generar(
        IDEA, "terror", progreso=lambda etapa, avance, _msg: avances.append((etapa, avance))
    )
    assert historia.completa
    assert historia.bible.genero == "terror"  # el género lo decide el usuario
    for n in range(1, 6):
        archivos = historia.escena(n)
        assert archivos.imagen and archivos.voz and archivos.ambiente and archivos.mezcla
        assert sf.info(str(archivos.mezcla)).samplerate == cfg.mix.sample_rate
    assert (historia.carpeta / "character_sheet.png").is_file()
    # La Bible guardada tiene las seeds que se usaron.
    assert all(e.seed_imagen is not None for e in historia.bible.escenas)

    manifest = json.loads((historia.carpeta / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tipo"] == TIPO_MANIFEST and manifest["estado"] == "completa"
    assert manifest["titulo"] == historia.bible.titulo
    assert set(manifest["etapas"]) == {"texto", "imagen", "voz", "sonido", "mezcla"}
    assert {"texto", "imagen", "voz", "sonido", "mezcla", "total"} <= set(manifest["segundos"])
    assert manifest["configuracion"]["profile"] == "rapido"
    assert "hardware" in manifest

    etapas = [e for e, _ in avances]
    assert etapas.index("texto") < etapas.index("imagen") < etapas.index("mezcla")
    assert [a for _, a in avances] == sorted(a for _, a in avances)  # el avance no retrocede
    assert avances[-1][1] == 1.0

    listadas = listar_historias([tmp_path])
    assert [h.carpeta for h in listadas] == [historia.carpeta]
    assert cargar_historia(historia.carpeta).titulo == historia.titulo


def test_entrada_invalida_no_crea_carpeta(cfg: config.AppConfig, tmp_path: Path) -> None:
    with pytest.raises(InputValidationError):
        _pipeline(cfg, tmp_path).generar("corta", "terror")
    assert list(tmp_path.iterdir()) == []


def test_si_falla_el_texto_queda_el_manifest(cfg: config.AppConfig, tmp_path: Path) -> None:
    def sin_ollama(*_: Any) -> Any:
        raise PipelineError("Ollama no responde")

    with pytest.raises(PipelineError, match="Ollama"):
        _pipeline(cfg, tmp_path, escribir=sin_ollama).generar(IDEA, "misterio")
    (carpeta,) = list(tmp_path.iterdir())
    manifest = json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["estado"] == "fallida" and "Ollama" in manifest["error"]
    assert listar_historias([tmp_path]) == []  # sin story.json no se lista


def test_sin_modelo_de_imagen_hay_ilustraciones_de_respaldo(
    cfg: config.AppConfig, tmp_path: Path
) -> None:
    class SinModelo:
        nombre = "roto"

        def cargar(self, _cfg: Any) -> Any:
            raise FileNotFoundError("'Lykon/dreamshaper-8' no está descargado")

        def liberar(self) -> None:
            return None

    historia = _pipeline(cfg, tmp_path, backend_imagen=SinModelo()).generar(IDEA, "fantasia")
    assert historia.completa
    assert "imagen:respaldo:todas" in historia.manifest["fallbacks"]
    assert historia.manifest["estado"] == "completa_con_fallbacks"


def test_sin_voz_queda_el_ambiente(cfg: config.AppConfig, tmp_path: Path) -> None:
    class SinVoz(VozSimulada):
        def cargar(self) -> None:
            raise RuntimeError("onnxruntime no disponible")

    historia = _pipeline(cfg, tmp_path, backend_voz=SinVoz()).generar(IDEA, "aventura")
    assert "voz:sin_narracion" in historia.manifest["fallbacks"]
    escena = historia.escena(1)
    assert escena.voz is None and escena.mezcla is None
    assert escena.ambiente is not None and escena.ambiente.name == "sfx_1.wav"
    assert escena.imagen is not None


def test_regenerar_escena_cambia_imagen_y_ambiente(cfg: config.AppConfig, tmp_path: Path) -> None:
    pipeline = _pipeline(cfg, tmp_path)
    historia = pipeline.generar(IDEA, "misterio")
    seed_antes = historia.bible.escena(3).seed_imagen
    otra_antes = historia.bible.escena(2).seed_imagen
    imagen_antes = (historia.carpeta / "scene_3.png").read_bytes()

    nueva = pipeline.regenerar_escena(historia.carpeta, 3)
    assert nueva.bible.escena(3).seed_imagen != seed_antes
    assert nueva.bible.escena(2).seed_imagen == otra_antes
    assert (nueva.carpeta / "scene_3.png").read_bytes() != imagen_antes
    assert nueva.escena(3).mezcla is not None
    (registro,) = nueva.manifest["regeneraciones"]
    assert registro["escena"] == 3 and registro["seed_imagen"] == nueva.bible.escena(3).seed_imagen
    otra = pipeline.regenerar_escena(historia.carpeta, 3)
    assert otra.bible.escena(3).seed_imagen not in {seed_antes, registro["seed_imagen"]}
    with pytest.raises(ValueError):
        pipeline.regenerar_escena(historia.carpeta, 6)


def test_dependencias_reales_por_defecto(cfg: config.AppConfig) -> None:
    pipeline = Pipeline(cfg)
    assert pipeline.deps == Dependencias()
    assert pipeline.raiz == config.OUTPUTS_DIR


def test_utilidades_de_almacenamiento(tmp_path: Path) -> None:
    assert slug("¡El Faro que se enciende solo!") == "el_faro_que_se_enciende_solo"
    assert slug("???") == "historia"
    assert nuevo_run_id("Una idea").endswith("_una_idea")
    vacia = archivos_escena(tmp_path, 1)
    assert not vacia.completa and vacia.imagen is None
