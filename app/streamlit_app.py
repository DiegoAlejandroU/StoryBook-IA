"""StoryBook IA · interfaz Streamlit (tarea 5.2).

Ejecutar desde la carpeta del proyecto (o con doble clic en ``StoryBook.cmd``):

    uv run streamlit run app/streamlit_app.py
    uv run streamlit run app/streamlit_app.py -- --mock     # sin GPU ni Ollama

Solo dibuja: la lógica está en ``storybook.pipeline``, ``storybook.storage`` y
``storybook.ui_logica`` (testeados sin Streamlit).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

from storybook import config, ui_logica
from storybook.pipeline import Pipeline, PipelineError
from storybook.schemas import Genero, InputValidationError
from storybook.sound.generator import audio_generativo_desactivado
from storybook.storage import HistoriaGuardada, cargar_historia, listar_historias

MODO_SIMULADO = ui_logica.es_mock(sys.argv)

st.set_page_config(page_title="StoryBook IA", page_icon="📖", layout="wide")


# ---------------------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------------------
def _estado() -> Any:
    estado = st.session_state
    estado.setdefault("historia", None)  # str con la carpeta de la historia abierta
    estado.setdefault("escena", 1)
    return estado


def _pipeline(perfil: str) -> Pipeline:
    cfg = config.load_config(perfil)
    if MODO_SIMULADO:
        from storybook.mock import dependencias_simuladas

        return Pipeline(cfg, dependencias_simuladas())
    return Pipeline(cfg)


def _abrir(carpeta: Path) -> None:
    estado = _estado()
    estado.historia = str(carpeta)
    estado.escena = 1


def _historia_abierta() -> HistoriaGuardada | None:
    ruta = _estado().historia
    if not ruta:
        return None
    try:
        return cargar_historia(Path(ruta))
    except Exception as exc:  # carpeta borrada o Bible inválida
        st.error(f"No se pudo abrir la historia: {exc}")
        _estado().historia = None
        return None


def _con_progreso(titulo: str, accion: Any) -> Any:
    """Ejecuta ``accion(progreso)`` mostrando un ``st.status`` con barra y etapas."""
    with st.status(titulo, expanded=True) as estado:
        barra = st.progress(0.0)
        vistas: set[str] = set()

        def progreso(etapa: str, avance: float, mensaje: str) -> None:
            barra.progress(min(max(avance, 0.0), 1.0), text=mensaje)
            if mensaje.endswith(": listo") and etapa not in vistas:
                vistas.add(etapa)
                st.write(f"✓ {mensaje.removesuffix(': listo')}")

        try:
            resultado = accion(progreso)
        except InputValidationError as exc:
            estado.update(label="Revisa los datos de la historia", state="error")
            st.error(str(exc))
            return None
        except PipelineError as exc:
            estado.update(label="No se pudo completar", state="error")
            st.error(str(exc))
            return None
        estado.update(label=f"{titulo}: listo", state="complete", expanded=False)
        return resultado


# ---------------------------------------------------------------------------------------
# Barra lateral: nueva historia e historias guardadas
# ---------------------------------------------------------------------------------------
def barra_lateral() -> None:
    with st.sidebar:
        st.title("StoryBook IA")
        if MODO_SIMULADO:
            st.warning("Modo simulado: sin GPU ni modelos. La historia es siempre la de ejemplo.")
        if audio_generativo_desactivado():
            st.warning(
                "Demostración de respaldo: el sonido generativo está desactivado. Los ambientes "
                "se crean con la síntesis procedural."
            )

        with st.form("nueva_historia"):
            st.subheader("Nueva historia")
            idea = st.text_area(
                "Idea",
                placeholder="Ej.: Un faro abandonado que se enciende solo cada noche",
                max_chars=500,
            )
            generos = ui_logica.opciones_genero()
            genero = st.selectbox(
                "Género", [g for g, _ in generos], format_func=dict(generos).__getitem__
            )
            genero_otro = st.text_input("Si elegiste «Otro», ¿cuál?", max_chars=40)
            perfil = st.radio(
                "Perfil",
                list(ui_logica.PERFILES),
                format_func=ui_logica.PERFILES.__getitem__,
            )
            enviar = st.form_submit_button("Generar historia", type="primary")
        if enviar:
            otro = genero_otro if genero == Genero.OTRO.value else None
            historia = _con_progreso(
                "Generando la historia",
                lambda progreso: _pipeline(perfil).generar(idea, genero, otro, progreso),
            )
            if historia is not None:
                _abrir(historia.carpeta)
                st.rerun()

        st.divider()
        st.subheader("Historias guardadas")
        entradas = listar_historias()
        if not entradas:
            st.caption("Aún no hay historias.")
            return
        elegida = st.selectbox(
            "Abrir",
            entradas,
            format_func=ui_logica.etiqueta_historia,
            label_visibility="collapsed",
        )
        if st.button("Abrir historia") and elegida is not None:
            _abrir(elegida.carpeta)
            st.rerun()


# ---------------------------------------------------------------------------------------
# Visor de escenas
# ---------------------------------------------------------------------------------------
def _audio(etiqueta: str, ruta: Path | None) -> None:
    st.markdown(f"**{etiqueta}**")
    if ruta is None:
        st.caption("No disponible")
    else:
        formato = "audio/ogg" if ruta.suffix == ".ogg" else "audio/wav"
        st.audio(ruta.read_bytes(), format=formato)


def visor(historia: HistoriaGuardada) -> None:
    estado = _estado()
    numero = ui_logica.mover(estado.escena, 0)
    escena = historia.bible.escena(numero)
    archivos = historia.escena(numero)

    st.title(historia.titulo)
    st.caption(
        f"{historia.bible.genero.capitalize()} · {historia.bible.tono} · "
        f"perfil {ui_logica.nombre_perfil(str(historia.manifest.get('perfil', '-')))}"
    )
    st.info(ui_logica.ETIQUETA_IA, icon=":material/smart_toy:")

    anterior, centro, siguiente = st.columns([1, 3, 1])
    if anterior.button("← Anterior", disabled=numero == 1):
        estado.escena = ui_logica.mover(numero, -1)
        st.rerun()
    centro.markdown(
        f"<div style='text-align:center'><b>{ui_logica.indicador(numero)}</b> · "
        f"{ui_logica.fase_legible(escena.fase)}</div>",
        unsafe_allow_html=True,
    )
    if siguiente.button("Siguiente →", disabled=numero == 5):
        estado.escena = ui_logica.mover(numero, 1)
        st.rerun()

    imagen, texto = st.columns([3, 2])
    with imagen:
        if archivos.imagen is not None:
            st.image(str(archivos.imagen))
        else:
            st.caption("Sin ilustración")
    with texto:
        st.markdown(escena.texto_narrativo)

    voz, ambiente, mezcla = st.columns(3)
    with voz:
        _audio("Narración", archivos.voz)
    with ambiente:
        _audio("Ambiente sonoro", archivos.ambiente)
    with mezcla:
        _audio("Voz + ambiente", archivos.mezcla)

    es_muestra = config.SAMPLES_DIR in historia.carpeta.parents
    if not es_muestra and st.button("Regenerar ilustración y ambiente de esta escena"):
        perfil = str(historia.manifest.get("perfil") or "rapido")
        nueva = _con_progreso(
            f"Regenerando la escena {numero}",
            lambda progreso: _pipeline(perfil).regenerar_escena(historia.carpeta, numero, progreso),
        )
        if nueva is not None:
            st.rerun()

    with st.expander("Detalles técnicos"):
        sonido = ui_logica.backend_sonido_por_escena(historia.manifest)
        total = historia.manifest.get("segundos", {}).get("total")
        st.write(
            f"Ambiente de esta escena: {ui_logica.nombre_backend(sonido.get(numero, '-'))}. "
            f"Tiempo total de generación: {ui_logica.segundos_legibles(total)}."
        )
        avisos = ui_logica.resumen_fallbacks(historia.manifest)
        if avisos:
            st.markdown("**Alternativas automáticas usadas:**")
            for aviso in avisos:
                st.markdown(f"- {aviso}")
        st.caption(f"Carpeta: {historia.carpeta}")


# ---------------------------------------------------------------------------------------
barra_lateral()
abierta = _historia_abierta()
if abierta is None:
    st.title("StoryBook IA")
    st.markdown(
        "Escribe una idea, elige el género y el perfil, y presiona **Generar historia**. "
        "Se crean 5 escenas con texto, ilustración, narración y ambiente sonoro, todo en este "
        "equipo y sin Internet. También puedes abrir una historia guardada."
    )
    st.info(ui_logica.ETIQUETA_IA, icon=":material/smart_toy:")
else:
    visor(abierta)
