"""Lógica de la UI (tarea 5.2) sin Streamlit."""

from __future__ import annotations

from pathlib import Path

from storybook import ui_logica
from storybook.storage import EntradaHistoria


def test_opciones_de_genero_en_orden_y_con_tildes() -> None:
    opciones = ui_logica.opciones_genero()
    assert opciones[0] == ("terror", "Terror")
    assert ("fantasia", "Fantasía") in opciones and (
        "ciencia_ficcion",
        "Ciencia ficción",
    ) in opciones
    assert opciones[-1][0] == "otro"


def test_navegacion_no_se_sale_de_1_a_5() -> None:
    assert ui_logica.mover(1, -1) == 1
    assert ui_logica.mover(5, 1) == 5
    assert ui_logica.mover(3, 1) == 4
    assert ui_logica.indicador(2) == "Escena 2/5"


def test_textos_legibles() -> None:
    assert ui_logica.fase_legible("climax") == "Clímax"
    assert ui_logica.segundos_legibles(None) == "-"
    assert ui_logica.segundos_legibles(42.4) == "42 s"
    assert ui_logica.segundos_legibles(135) == "2 min 15 s"
    assert ui_logica.nombre_backend("audioldm") == "AudioLDM"
    assert ui_logica.nombre_perfil("rapido") == "rápido"


def test_fallbacks_en_espanol() -> None:
    manifest = {
        "fallbacks": ["sonido:sa3:no_disponible", "imagen:respaldo:3", "codigo_nuevo"],
        "regeneraciones": [{"escena": 2, "fallbacks": ["sonido:escena_2:audioldm_fallo"]}],
    }
    avisos = ui_logica.resumen_fallbacks(manifest)
    assert avisos[0].startswith("Sonido: Stable Audio 3 Small-SFX no estaba disponible")
    assert avisos[1] == "Imagen de la escena 3: ilustración de respaldo."
    assert avisos[2] == "codigo_nuevo"  # lo desconocido se muestra tal cual
    assert "falló AudioLDM" in avisos[3]


def test_backend_de_sonido_por_escena_con_regeneraciones() -> None:
    manifest = {
        "etapas": {"sonido": {"sonidos": [{"escena": 1, "backend": "audioldm"}]}},
        "regeneraciones": [{"escena": 1, "sonido_backend": "procedural"}],
    }
    assert ui_logica.backend_sonido_por_escena(manifest) == {1: "procedural"}
    assert ui_logica.backend_sonido_por_escena({}) == {}


def test_etiqueta_de_historia_y_modo_simulado(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    entrada = EntradaHistoria(
        Path("x"), "El Faro", "misterio", "2026-11-10T13:05:00", "samples", "rapido"
    )
    assert ui_logica.etiqueta_historia(entrada) == "El Faro · misterio · 2026-11-10 13:05 · ejemplo"
    assert ui_logica.es_mock(["app.py", "--mock"])
    monkeypatch.delenv("STORYBOOK_MOCK", raising=False)
    assert not ui_logica.es_mock(["app.py"])
    monkeypatch.setenv("STORYBOOK_MOCK", "1")
    assert ui_logica.es_mock(["app.py"])
