"""Tests de la etapa de imágenes con un pipeline falso (sin torch, diffusers ni pesos)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from storybook.config import ConsistencyConfig, ImageConfig, load_config
from storybook.image.consistency import NOMBRE_ARCHIVO_SHEET
from storybook.image.generator import (
    FALLBACK_RESPALDO,
    FALLBACK_SIN_IP_ADAPTER,
    GeneradorImagenes,
    ImageModelError,
    imagen_respaldo,
    nombre_archivo_escena,
)
from storybook.schemas import StoryBible


class FakeOOM(RuntimeError):
    """Hace de ``torch.cuda.OutOfMemoryError``."""


class FakeTokenizer:
    def __call__(self, texto: str, add_special_tokens: bool = True) -> dict[str, list[int]]:
        return {"input_ids": list(range(len(texto.replace(",", " ").split())))}


class FakePipe:
    def __init__(self, backend: FakeBackend) -> None:
        self.tokenizer = FakeTokenizer()
        self._backend = backend

    def __call__(self, **kwargs: Any) -> Any:
        self._backend.llamadas.append(kwargs)
        indice = len(self._backend.llamadas)
        if indice in self._backend.fallos:
            raise self._backend.fallos[indice]
        imagen = Image.new("RGB", (kwargs["width"], kwargs["height"]), (indice * 20 % 255, 0, 0))
        return type("Salida", (), {"images": [imagen]})()


class FakeBackend:
    nombre = "fake"

    def __init__(
        self,
        *,
        fallar_carga: bool = False,
        fallar_ip: bool = False,
        fallos: dict[int, Exception] | None = None,
    ) -> None:
        self.llamadas: list[dict[str, Any]] = []
        self.fallos = fallos or {}
        self.fallar_carga = fallar_carga
        self.fallar_ip = fallar_ip
        self.ip_preparado_con: Image.Image | None = None
        self.liberado = 0

    def cargar(self, cfg: ImageConfig) -> FakePipe:
        if self.fallar_carga:
            raise FileNotFoundError("'Lykon/dreamshaper-8' no está descargado")
        return FakePipe(self)

    def preparar_ip_adapter(self, pipe: Any, cfg: ImageConfig, referencia: Image.Image) -> Any:
        if self.fallar_ip:
            raise RuntimeError("IP-Adapter incompatible")
        self.ip_preparado_con = referencia
        return ["embeds"]

    def generador(self, seed: int) -> Any:
        return ("gen", seed)

    def es_oom(self, exc: BaseException) -> bool:
        return isinstance(exc, FakeOOM)

    def liberar(self) -> None:
        self.liberado += 1

    def info(self) -> dict[str, Any]:
        return {"backend": self.nombre}


@pytest.fixture
def bible(bible_dict: dict) -> StoryBible:
    return StoryBible.model_validate(bible_dict)


def _generador(
    backend: FakeBackend, *, ip: bool = True, consistencia: ConsistencyConfig | None = None
) -> GeneradorImagenes:
    base = load_config("default").image
    cfg = base.model_copy(update={"ip_adapter": base.ip_adapter.model_copy(update={"enabled": ip})})
    return GeneradorImagenes(cfg, consistencia or ConsistencyConfig(), backend)


def test_genera_cinco_escenas_con_character_sheet(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeBackend()
    etapa = _generador(backend).generar(bible, tmp_path)

    assert [r.escena for r in etapa.imagenes] == [1, 2, 3, 4, 5]
    for r in etapa.imagenes:
        assert r.ruta == tmp_path / nombre_archivo_escena(r.escena)
        assert Image.open(r.ruta).size == (768, 512)
        assert r.ip_adapter and not r.respaldo
    # 1 llamada para la character sheet (cuadrada, sin IP-Adapter) + 5 escenas con embeds.
    assert len(backend.llamadas) == 6
    sheet = backend.llamadas[0]
    assert (sheet["width"], sheet["height"]) == (512, 512)
    assert "ip_adapter_image_embeds" not in sheet
    assert all(c["ip_adapter_image_embeds"] == ["embeds"] for c in backend.llamadas[1:])
    assert etapa.character_sheet == tmp_path / NOMBRE_ARCHIVO_SHEET
    assert etapa.character_sheet.is_file()
    assert backend.ip_preparado_con is not None
    assert backend.liberado == 1
    assert etapa.fallbacks == [] and etapa.errores == []


def test_parametros_constantes_y_seeds_registradas(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeBackend()
    gen = _generador(backend)
    etapa = gen.generar(bible, tmp_path)

    escenas = backend.llamadas[1:]
    assert {c["num_inference_steps"] for c in escenas} == {gen.cfg.steps}
    assert {c["guidance_scale"] for c in escenas} == {gen.cfg.guidance_scale}
    # Política "compartida": todas las escenas usan la seed del protagonista.
    seed_prota = etapa.bible.protagonista().seed
    assert seed_prota is not None
    assert {c["generator"] for c in escenas} == {("gen", seed_prota)}
    assert [r.seed for r in etapa.imagenes] == [seed_prota] * 5
    datos = etapa.a_dict()
    assert datos["parametros"]["ip_adapter"] is True
    assert datos["imagenes"][0]["prompt"]["tokens"] <= 75
    assert datos["character_sheet"] == NOMBRE_ARCHIVO_SHEET


def test_seeds_reproducibles_entre_ejecuciones(bible: StoryBible, tmp_path: Path) -> None:
    a = _generador(FakeBackend()).generar(bible, tmp_path / "a")
    b = _generador(FakeBackend()).generar(bible, tmp_path / "b")
    assert [r.seed for r in a.imagenes] == [r.seed for r in b.imagenes]
    assert [r.prompt.prompt for r in a.imagenes] == [r.prompt.prompt for r in b.imagenes]


def test_seeds_por_escena(bible: StoryBible, tmp_path: Path) -> None:
    consistencia = ConsistencyConfig(seed_policy="por_escena")
    etapa = _generador(FakeBackend(), consistencia=consistencia).generar(bible, tmp_path)
    assert len({r.seed for r in etapa.imagenes}) == 5


def test_c1_sin_bible_ni_ip_adapter(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeBackend()
    consistencia = ConsistencyConfig(use_bible=False, fixed_seed=False, seed_policy="por_escena")
    etapa = _generador(backend, ip=True, consistencia=consistencia).generar(bible, tmp_path)

    assert len(backend.llamadas) == 5  # sin character sheet
    assert etapa.character_sheet is None
    assert not etapa.parametros["ip_adapter"]
    for r in etapa.imagenes:
        assert r.prompt.prompt == bible.escena(r.escena).prompt_imagen
        assert not r.ip_adapter


def test_c2_sin_ip_adapter(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeBackend()
    etapa = _generador(backend, ip=False).generar(bible, tmp_path)
    assert len(backend.llamadas) == 5
    assert all("ip_adapter_image_embeds" not in c for c in backend.llamadas)
    assert etapa.character_sheet is None


def test_fallo_de_ip_adapter_sigue_sin_el(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeBackend(fallar_ip=True)
    etapa = _generador(backend).generar(bible, tmp_path)
    assert FALLBACK_SIN_IP_ADAPTER in etapa.fallbacks
    assert len(etapa.imagenes) == 5
    assert all(not r.ip_adapter for r in etapa.imagenes)
    assert all("ip_adapter_image_embeds" not in c for c in backend.llamadas[1:])


def test_oom_se_reintenta_una_vez(bible: StoryBible, tmp_path: Path) -> None:
    # Llamada 1 = sheet, 2 = escena 1 (OOM), 3 = reintento de la escena 1.
    backend = FakeBackend(fallos={2: FakeOOM("CUDA out of memory")})
    etapa = _generador(backend).generar(bible, tmp_path)
    primera = etapa.imagenes[0]
    assert primera.intentos == 2 and not primera.respaldo
    assert etapa.fallbacks == []


def test_fallo_persistente_usa_imagen_de_respaldo(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeBackend(fallos={3: ValueError("NaN en el VAE")})  # escena 2
    etapa = _generador(backend).generar(bible, tmp_path)
    segunda = etapa.imagenes[1]
    assert segunda.respaldo and segunda.intentos == 1
    assert "NaN" in (segunda.error or "")
    assert segunda.ruta.is_file()
    assert f"{FALLBACK_RESPALDO}:2" in etapa.fallbacks
    assert len(etapa.imagenes) == 5
    assert sum(r.respaldo for r in etapa.imagenes) == 1


def test_oom_persistente_usa_respaldo(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeBackend(fallos={2: FakeOOM("oom"), 3: FakeOOM("oom")})
    etapa = _generador(backend).generar(bible, tmp_path)
    assert etapa.imagenes[0].respaldo and etapa.imagenes[0].intentos == 2


def test_error_de_carga_libera_y_lanza(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeBackend(fallar_carga=True)
    with pytest.raises(ImageModelError, match="no está descargado"):
        _generador(backend).generar(bible, tmp_path)
    assert backend.liberado == 1


def test_regenerar_una_escena_reutiliza_sheet(bible: StoryBible, tmp_path: Path) -> None:
    _generador(FakeBackend()).generar(bible, tmp_path)
    backend = FakeBackend()
    etapa = _generador(backend).generar(bible, tmp_path, numeros=[3])
    assert [r.escena for r in etapa.imagenes] == [3]
    assert len(backend.llamadas) == 1  # sin regenerar la character sheet
    assert backend.ip_preparado_con is not None


def test_bible_con_seeds_no_se_modifica(bible: StoryBible, tmp_path: Path) -> None:
    con_seeds = bible.con_seeds(99)
    etapa = _generador(FakeBackend()).generar(con_seeds, tmp_path)
    assert etapa.bible is con_seeds


def test_imagen_respaldo_tamano() -> None:
    imagen = imagen_respaldo(768, 512, 4)
    assert imagen.size == (768, 512) and imagen.mode == "RGB"


def test_backend_real_no_importa_torch_al_crear() -> None:
    import sys

    from storybook.image.generator import DiffusersBackend

    backend = DiffusersBackend()
    assert backend.info() == {}
    if "torch" not in sys.modules:
        assert backend.es_oom(RuntimeError("x")) is False
