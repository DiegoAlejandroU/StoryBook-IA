"""Lógica de la interfaz sin Streamlit (testeable): opciones, navegación y textos legibles.

``app/streamlit_app.py`` solo dibuja; todo lo que decide qué mostrar vive aquí.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from storybook.schemas import FASE_POR_NUMERO, GENERO_ETIQUETA, Fase, Genero
from storybook.storage import NUM_ESCENAS, ArchivosEscena, EntradaHistoria, HistoriaGuardada

PERFILES: Final[dict[str, str]] = {
    # Con la generación por escenas la primera aparece mucho antes que la historia completa;
    # los tiempos se miden en el equipo de referencia (docs/evidencias) y van en el panel.
    "rapido": "Rápido (6 pasos por imagen)",
    "calidad": "Calidad (25 pasos por imagen)",
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


# ---------------------------------------------------------------------------------------
# Libro: lo que se dibuja de una historia, terminada o en curso (generación por escenas)
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Pagina:
    """Una escena lista para mostrarse (texto, archivos y detalles técnicos)."""

    numero: int
    fase: str
    texto: str
    archivos: ArchivosEscena
    detalles: dict[str, Any]
    lista_en_s: float | None = None


@dataclass(frozen=True)
class VistaLibro:
    titulo: str
    genero: str
    tono: str
    perfil: str
    paginas: dict[int, Pagina]
    resumenes: list[str] = field(default_factory=list)
    personajes: dict[str, str] = field(default_factory=dict)  # id -> nombre
    configuracion: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    carpeta: Path | None = None
    en_curso: int | None = None
    terminada: bool = True

    def estado(self, numero: int) -> str:
        """ "lista", "en_curso" o "pendiente" (para el selector de escenas)."""
        if numero in self.paginas:
            return "lista"
        return "en_curso" if numero == self.en_curso else "pendiente"

    def navegable(self, numero: int) -> bool:
        """Se puede abrir una escena lista y también la que se está generando."""
        return self.estado(numero) != "pendiente"


def detalles_desde_manifest(manifest: dict[str, Any], numero: int) -> dict[str, Any]:
    """Imagen, voz, ambiente y mezcla de la escena ``numero`` según el manifest (con las
    regeneraciones aplicadas: la última manda)."""
    etapas = manifest.get("etapas", {})

    def de(etapa: str, lista: str) -> dict[str, Any] | None:
        for item in etapas.get(etapa, {}).get(lista, []) or []:
            if int(item.get("escena", 0)) == numero:
                return dict(item)
        return None

    detalles: dict[str, Any] = {
        "imagen": de("imagen", "imagenes"),
        "voz": de("voz", "narraciones"),
        "sonido": de("sonido", "sonidos"),
        "mezcla": de("mezcla", "mezclas"),
    }
    for regeneracion in manifest.get("regeneraciones", []):
        if regeneracion.get("escena") == numero:
            imagenes = regeneracion.get("imagen", {}).get("imagenes", [])
            nueva = next((i for i in imagenes if int(i.get("escena", 0)) == numero), None)
            if nueva:
                detalles["imagen"] = dict(nueva)
            backend = regeneracion.get("sonido_backend")
            if backend and detalles["sonido"]:
                detalles["sonido"] = {**detalles["sonido"], "backend": backend}
    listas = {int(x["escena"]): x.get("lista_en_s") for x in manifest.get("escenas_listas", [])}
    if numero in listas:
        detalles["lista_en_s"] = listas[numero]
    return {k: v for k, v in detalles.items() if v is not None}


def vista_de_historia(historia: HistoriaGuardada) -> VistaLibro:
    bible, manifest = historia.bible, historia.manifest
    paginas = {
        e.numero: Pagina(
            numero=e.numero,
            fase=str(e.fase),
            texto=e.texto_narrativo,
            archivos=historia.escena(e.numero),
            detalles=(detalles := detalles_desde_manifest(manifest, e.numero)),
            lista_en_s=detalles.get("lista_en_s"),
        )
        for e in bible.escenas
    }
    return VistaLibro(
        titulo=bible.titulo,
        genero=str(bible.genero or manifest.get("genero", "")),
        tono=bible.tono,
        perfil=str(manifest.get("perfil") or "-"),
        paginas=paginas,
        resumenes=[e.resumen for e in bible.escenas],
        personajes={p.id: p.nombre for p in bible.personajes},
        configuracion=dict(manifest.get("configuracion") or {}),
        manifest=manifest,
        carpeta=historia.carpeta,
    )


def vista_en_vivo(instantanea: Any, configuracion: dict[str, Any]) -> VistaLibro:
    """Vista de una historia que se está generando (``Instantanea`` de la generación)."""
    plan = instantanea.plan
    paginas = {
        n: Pagina(
            numero=n,
            fase=str(lista.escena.fase),
            texto=lista.escena.texto_narrativo,
            archivos=lista.archivos,
            detalles={**lista.detalles, "lista_en_s": lista.lista_en_s},
            lista_en_s=lista.lista_en_s,
        )
        for n, lista in sorted(instantanea.listas.items())
    }
    return VistaLibro(
        titulo=plan.titulo if plan else "",
        genero=plan.genero if plan else "",
        tono=plan.tono if plan else "",
        perfil=instantanea.perfil,
        paginas=paginas,
        resumenes=list(plan.resumenes) if plan else [],
        personajes=dict(plan.personajes) if plan else {},
        configuracion=configuracion,
        carpeta=instantanea.carpeta,
        en_curso=instantanea.en_curso,
        terminada=bool(instantanea.terminada),
    )


def _num(valor: Any, decimales: int = 1) -> str:
    try:
        texto = f"{float(valor):.{decimales}f}"
    except (TypeError, ValueError):
        return "-"
    return texto.replace(".", ",")


def filas_escena(detalles: dict[str, Any], personajes: dict[str, str]) -> list[tuple[str, str]]:
    """Datos técnicos de una escena para el panel derecho: (etiqueta, valor)."""
    filas: list[tuple[str, str]] = []
    imagen = detalles.get("imagen") or {}
    if imagen:
        if imagen.get("respaldo"):
            filas.append(("Ilustración", "de respaldo (el modelo falló)"))
        prompt = imagen.get("prompt") or {}
        foco = prompt.get("foco")
        if foco:
            nombre = personajes.get(str(foco), str(foco).replace("_", " ").title())
            filas.append(("Personaje en foco", nombre))
        escala = imagen.get("ip_escala")
        filas.append(
            (
                "Referencia del protagonista",
                f"IP-Adapter {_num(escala, 2)}" if escala else "no se aplica en esta escena",
            )
        )
        filas.append(("Seed de la imagen", str(imagen.get("seed", "-"))))
        filas.append(("Tiempo de la imagen", f"{_num(imagen.get('segundos'))} s"))
    voz = detalles.get("voz") or {}
    if voz:
        filas.append(("Narración", f"{_num(voz.get('duracion_s'))} s de audio"))
    sonido = detalles.get("sonido") or {}
    if sonido:
        filas.append(("Ambiente", nombre_backend(str(sonido.get("backend", "-")))))
    mezcla = detalles.get("mezcla") or {}
    if "lufs_voz" in mezcla:
        bajo = _num(mezcla.get("ambiente_bajo_voz_db"), 0)
        filas.append(
            ("Mezcla", f"voz a {_num(mezcla['lufs_voz'])} LUFS, ambiente {bajo} dB por debajo")
        )
    if detalles.get("lista_en_s") is not None:
        filas.append(("Lista a los", segundos_legibles(detalles["lista_en_s"])))
    return filas


def prompts_escena(detalles: dict[str, Any]) -> dict[str, str]:
    """Prompts usados en la escena (imagen y ambiente), para mostrarlos plegados."""
    prompts: dict[str, str] = {}
    imagen = (detalles.get("imagen") or {}).get("prompt") or {}
    if imagen.get("prompt"):
        prompts["Ilustración"] = str(imagen["prompt"])
    sonido = detalles.get("sonido") or {}
    efectivo = (sonido.get("detalle") or {}).get("prompt_efectivo") or sonido.get("prompt")
    if efectivo:
        prompts["Ambiente"] = str(efectivo)
    return prompts


MODELOS_IMAGEN: Final[dict[str, str]] = {
    "Lykon/dreamshaper-8": "DreamShaper 8 (SD 1.5)",
    "Lykon/dreamshaper-xl-lightning": "DreamShaper XL Lightning (SDXL)",
}


def filas_historia(vista: VistaLibro) -> list[tuple[str, str]]:
    """Modelos y tiempos de la historia (panel derecho)."""
    cfg = vista.configuracion
    llm, imagen, voz, sonido = (cfg.get(k) or {} for k in ("llm", "image", "voice", "sound"))
    filas: list[tuple[str, str]] = [("Perfil", nombre_perfil(vista.perfil))]
    if llm.get("model"):
        filas.append(("Texto", str(llm["model"]).replace("-instruct-2507-q4_K_M", " (Q4)")))
    if imagen.get("model_id"):
        modelo = MODELOS_IMAGEN.get(str(imagen["model_id"]), str(imagen["model_id"]))
        pasos = imagen.get("steps")
        filas.append(("Imágenes", f"{modelo}, {pasos} pasos" if pasos else modelo))
    if voz.get("piper_voice"):
        filas.append(("Voz", f"Piper {voz['piper_voice']}"))
    if sonido.get("backends"):
        cadena = [nombre_backend(b) for b in sonido["backends"]]
        filas.append(("Ambiente", " → ".join(cadena)))
    segundos = vista.manifest.get("segundos", {}) if vista.manifest else {}
    if segundos.get("primera_escena") is not None:
        filas.append(("Primera escena", segundos_legibles(segundos["primera_escena"])))
    if segundos.get("total") is not None:
        filas.append(("Historia completa", segundos_legibles(segundos["total"])))
    return filas


FASE_POR_ESCENA: Final[dict[int, Fase]] = dict(FASE_POR_NUMERO)


def subtitulo(vista: VistaLibro) -> str:
    """Género y tono bajo el título ("Misterio, inquietante y tierno")."""
    partes = [p for p in (str(vista.genero).capitalize(), vista.tono) if p]
    return ", ".join(partes)
