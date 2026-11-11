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
    # Tiempos medidos en el equipo de referencia (batería 6.2: 124-129 s por historia en rápido;
    # calidad suma unos 30 s de imágenes con 25 pasos).
    "rapido": "Rápido · unos 2 minutos",
    "calidad": "Calidad · imágenes con 25 pasos, unos 3 minutos",
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


ORDEN_SONIDO: Final = ("sa3", "sao", "audioldm", "library", "procedural")
_POR_ESCENA: Final = re.compile(r"^(?:(sonido):escena_(\d+):|(imagen):respaldo:(\d+)$)")


def _escena_del_codigo(codigo: str) -> tuple[str, int] | None:
    """("sonido", 2) para "sonido:escena_2:audioldm_fallo"; ("imagen", 3) para
    "imagen:respaldo:3"; None si el código no es de una escena."""
    m = _POR_ESCENA.match(codigo)
    if not m:
        return None
    return (m.group(1), int(m.group(2))) if m.group(1) else (m.group(3), int(m.group(4)))


def fallbacks_vigentes(manifest: dict[str, Any]) -> list[str]:
    """Alternativas que siguen describiendo la historia tal como está ahora.

    - Al regenerar una escena (o rehacer su sonido), los avisos anteriores de esa escena
      dejan de valer: la escena 2 pudo fallar con AudioLDM y, al rehacerla, salir con él.
    - "<backend> no estaba disponible" solo se muestra si alguna escena usa un backend
      posterior en la cadena. Si todas salieron con AudioLDM, que la biblioteca no estuviera
      no afectó a nada.
    """
    codigos = list(manifest.get("fallbacks", []))
    for regeneracion in manifest.get("regeneraciones", []):
        escenas = set(regeneracion.get("escenas") or [])
        if "escena" in regeneracion:
            escenas.add(int(regeneracion["escena"]))
        solo_sonido = regeneracion.get("tipo") == "sonido"

        def cubierto(codigo: str, escenas: set[int] = escenas, solo: bool = solo_sonido) -> bool:
            escena = _escena_del_codigo(codigo)
            return (
                escena is not None and escena[1] in escenas and (not solo or escena[0] == "sonido")
            )

        codigos = [c for c in codigos if not cubierto(c)] + list(regeneracion.get("fallbacks", []))

    usados = [
        ORDEN_SONIDO.index(b)
        for b in backend_sonido_por_escena(manifest).values()
        if b in ORDEN_SONIDO
    ]
    ultimo = max(usados, default=len(ORDEN_SONIDO))

    def vigente(codigo: str) -> bool:
        partes = codigo.split(":")
        if len(partes) == 3 and partes[0] == "sonido" and partes[2] == "no_disponible":
            return partes[1] not in ORDEN_SONIDO or ORDEN_SONIDO.index(partes[1]) < ultimo
        return True

    return list(dict.fromkeys(c for c in codigos if vigente(c)))


def resumen_fallbacks(manifest: dict[str, Any]) -> list[str]:
    return [fallback_legible(c) for c in fallbacks_vigentes(manifest)]


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
