"""Lógica de la interfaz sin Streamlit (testeable): opciones, navegación y textos legibles.

``app/streamlit_app.py`` solo dibuja; todo lo que decide qué mostrar vive aquí.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final

from storybook.schemas import GENERO_ETIQUETA, Fase, Genero
from storybook.storage import NUM_ESCENAS, EntradaHistoria

PERFILES: Final[dict[str, str]] = {
    "rapido": "Rápido · unos 3 a 5 minutos",
    "calidad": "Calidad · imágenes y sonido más elaborados, unos 5 a 12 minutos",
}
FASES: Final[dict[str, str]] = {
    Fase.INICIO.value: "Inicio",
    Fase.DESARROLLO.value: "Desarrollo",
    Fase.CLIMAX.value: "Clímax",
    Fase.DESENLACE.value: "Desenlace",
}
NOMBRES_BACKEND: Final[dict[str, str]] = {
    "sa3": "Stable Audio 3 Small-SFX",
    "sao": "Stable Audio Open 1.0",
    "audioldm": "AudioLDM",
    "library": "biblioteca CC0",
    "procedural": "síntesis procedural",
    "simulado": "simulado",
}
NOMBRE_PERFIL: Final[dict[str, str]] = {"rapido": "rápido", "calidad": "calidad"}
ETIQUETA_IA: Final = "Contenido generado por IA (texto, imágenes, voz y sonido), en este equipo."


def opciones_genero() -> list[tuple[str, str]]:
    """(valor, etiqueta) en el orden del enunciado; "otro" al final."""
    return [(g.value, GENERO_ETIQUETA[g].capitalize()) for g in Genero]


def mover(escena: int, delta: int, total: int = NUM_ESCENAS) -> int:
    """Navegación Anterior/Siguiente sin salirse de 1..total."""
    return max(1, min(total, escena + delta))


def indicador(escena: int, total: int = NUM_ESCENAS) -> str:
    return f"Escena {escena}/{total}"


def fase_legible(fase: str) -> str:
    return FASES.get(str(fase), str(fase).capitalize())


def segundos_legibles(segundos: float | None) -> str:
    if segundos is None:
        return "-"
    total = round(segundos)
    if total < 60:
        return f"{total} s"
    return f"{total // 60} min {total % 60:02d} s"


def nombre_backend(nombre: str) -> str:
    return NOMBRES_BACKEND.get(nombre, nombre)


def backend_sonido_por_escena(manifest: dict[str, Any]) -> dict[int, str]:
    """Backend que produjo el ambiente de cada escena (incluye regeneraciones)."""
    sonidos = manifest.get("etapas", {}).get("sonido", {}).get("sonidos", [])
    resultado = {int(s["escena"]): str(s["backend"]) for s in sonidos if "escena" in s}
    for regeneracion in manifest.get("regeneraciones", []):
        if "sonido_backend" in regeneracion:
            resultado[int(regeneracion["escena"])] = str(regeneracion["sonido_backend"])
    return resultado


_SIGUIENTE: Final = "se usó el siguiente de la cadena."
_PATRONES_FALLBACK: Final = (
    (
        re.compile(r"^sonido:(\w+):no_disponible$"),
        "Sonido: {0} no estaba disponible; " + _SIGUIENTE,
    ),
    (
        re.compile(r"^sonido:escena_(\d+):(\w+)_fallo$"),
        "Sonido de la escena {0}: falló {1}; " + _SIGUIENTE,
    ),
    (
        re.compile(r"^imagen:respaldo:todas$"),
        "Imágenes: el modelo no cargó; ilustraciones de respaldo.",
    ),
    (re.compile(r"^imagen:respaldo:(\d+)$"), "Imagen de la escena {0}: ilustración de respaldo."),
    (
        re.compile(r"^imagen:sin_ip_adapter$"),
        "Imágenes: sin IP-Adapter (consistencia solo por texto).",
    ),
    (
        re.compile(r"^voz:sin_narracion$"),
        "Voz: no se pudo narrar; la historia queda sin voz ni mezcla.",
    ),
)


def fallback_legible(codigo: str) -> str:
    for patron, plantilla in _PATRONES_FALLBACK:
        coincidencia = patron.match(codigo)
        if coincidencia:
            partes = [nombre_backend(g) if not g.isdigit() else g for g in coincidencia.groups()]
            return plantilla.format(*partes)
    return codigo


def resumen_fallbacks(manifest: dict[str, Any]) -> list[str]:
    codigos = list(manifest.get("fallbacks", []))
    for regeneracion in manifest.get("regeneraciones", []):
        codigos += regeneracion.get("fallbacks", [])
    return [fallback_legible(c) for c in dict.fromkeys(codigos)]


def etiqueta_historia(entrada: EntradaHistoria) -> str:
    fecha = entrada.fecha.replace("T", " ")[:16] if entrada.fecha else "sin fecha"
    origen = " · ejemplo" if entrada.origen == "samples" else ""
    genero = f" · {entrada.genero}" if entrada.genero else ""
    return f"{entrada.titulo}{genero} · {fecha}{origen}"


def es_mock(argv: Sequence[str]) -> bool:
    """``streamlit run app/streamlit_app.py -- --mock`` o la variable STORYBOOK_MOCK=1."""
    import os

    return "--mock" in argv or os.environ.get("STORYBOOK_MOCK", "") == "1"


def nombre_perfil(perfil: str) -> str:
    return NOMBRE_PERFIL.get(perfil, perfil)
