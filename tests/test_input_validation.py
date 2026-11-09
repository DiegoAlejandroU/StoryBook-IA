"""Validación de las dos únicas entradas: idea y género."""

from __future__ import annotations

import pytest

from storybook.schemas import Genero, InputValidationError, validar_entrada


def test_entrada_valida_normaliza_espacios() -> None:
    solicitud = validar_entrada("   Un faro   que se enciende solo   ", "misterio")
    assert solicitud.idea == "Un faro que se enciende solo"
    assert solicitud.genero is Genero.MISTERIO
    assert solicitud.genero_efectivo == "misterio"


@pytest.mark.parametrize("idea", ["", "     ", "corta", "!!!!!!!!!!!!"])
def test_idea_vacia_o_insuficiente(idea: str) -> None:
    with pytest.raises(InputValidationError) as info:
        validar_entrada(idea, "terror")
    assert info.value.mensajes
    assert all(isinstance(m, str) and m for m in info.value.mensajes)


def test_idea_demasiado_larga() -> None:
    with pytest.raises(InputValidationError, match="máximo"):
        validar_entrada("a" * 601, "fantasia")


def test_genero_invalido() -> None:
    with pytest.raises(InputValidationError, match="Opciones"):
        validar_entrada("Un robot que aprende a pintar", "romance_epico")


def test_genero_otro_requiere_texto() -> None:
    with pytest.raises(InputValidationError, match="otro"):
        validar_entrada("Un robot que aprende a pintar", "otro", "  ")


def test_genero_otro_con_texto() -> None:
    solicitud = validar_entrada("Un robot que aprende a pintar", "otro", "  fábula  ")
    assert solicitud.genero_efectivo == "fábula"


def test_genero_otro_se_ignora_si_no_aplica() -> None:
    solicitud = validar_entrada("Un dragón que teme a las alturas", "fantasia", "western")
    assert solicitud.genero_otro is None
    assert solicitud.genero_efectivo == "fantasía"
