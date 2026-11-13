"""StoryBook IA · interfaz Streamlit con forma de libro (tarea 5.2, rediseño del 12 nov).

Ejecutar desde la carpeta del proyecto (o con doble clic en ``StoryBook.cmd``):

    uv run streamlit run app/streamlit_app.py
    uv run streamlit run app/streamlit_app.py -- --mock     # sin GPU ni Ollama
    set STORYBOOK_MOCK_DEMORA=3   (simulado: 3 s por llamada al LLM, para ver el avance)

Tres zonas sin scroll: a la izquierda la barra para crear o abrir historias; al centro un
libro abierto (ilustración en la página izquierda, texto en la derecha) que se hojea con los
botones o con las teclas ← y →; a la derecha los detalles técnicos de la escena y la historia.

La historia se genera por escenas en segundo plano (``storybook.generacion_en_curso``): la
escena 1 aparece apenas está lista y las demás se van agregando mientras se lee. La interfaz
consulta el avance cada segundo con ``st.fragment(run_every=…)``.

Solo dibuja: la lógica está en ``storybook.pipeline``, ``storybook.progresivo``,
``storybook.storage`` y ``storybook.ui_logica`` (testeados sin Streamlit).
"""

from __future__ import annotations

import functools
import html
import sys
from pathlib import Path
from typing import Any

import streamlit as st

from storybook import config, ui_logica
from storybook.generacion_en_curso import CANDADO_GPU, GeneracionEnCurso, Instantanea
from storybook.pipeline import Pipeline, PipelineError
from storybook.schemas import Genero, InputValidationError, validar_entrada
from storybook.sound.generator import audio_generativo_desactivado
from storybook.storage import NUM_ESCENAS, cargar_historia, listar_historias

MODO_SIMULADO = ui_logica.es_mock(sys.argv)
CONSULTA_S = 1.0  # cada cuánto se mira el avance de la generación

st.set_page_config(
    page_title="StoryBook IA", page_icon="📖", layout="wide", initial_sidebar_state="expanded"
)


# ---------------------------------------------------------------------------------------
# Estilo: el libro abierto sobre la tela de la encuadernación
# ---------------------------------------------------------------------------------------
def _css() -> str:
    # Una animación por escena y sentido: al cambiar de escena cambia el nombre de la
    # animación y el navegador la vuelve a reproducir (la hoja que gira desde el lomo).
    giros = "\n".join(
        f"""
.st-key-libro_{n}_adelante .st-key-pagina_der {{ animation: hoja_ad_{n} .55s ease-out; }}
.st-key-libro_{n}_adelante .st-key-pagina_izq {{ animation: aparece_{n} .55s ease-out; }}
.st-key-libro_{n}_atras .st-key-pagina_izq {{ animation: hoja_at_{n} .55s ease-out; }}
.st-key-libro_{n}_atras .st-key-pagina_der {{ animation: aparece_{n} .55s ease-out; }}
@keyframes hoja_ad_{n} {{
    from {{ transform: perspective(1600px) rotateY(-78deg); opacity: .25; }}
    to {{ transform: perspective(1600px) rotateY(0); opacity: 1; }}
}}
@keyframes hoja_at_{n} {{
    from {{ transform: perspective(1600px) rotateY(78deg); opacity: .25; }}
    to {{ transform: perspective(1600px) rotateY(0); opacity: 1; }}
}}
@keyframes aparece_{n} {{ from {{ opacity: .35; }} to {{ opacity: 1; }} }}"""
        for n in range(NUM_ESCENAS + 1)
    )
    return f"""
<style>
:root {{
    --tela: #1F3D3E;
    --tela-clara: #2A5254;
    --papel: #FAF6EC;
    --papel-borde: #E4DAC2;
    --tinta: #2B2520;
    --tinta-suave: #6E6458;
    --oro: #D2AE5B;
    --oro-sobre-papel: #8A6A22;
    --texto-tela: #ECE7DA;
    --texto-tela-suave: #A9BAB4;
    --alto-pagina: clamp(300px, calc(100vh - 205px), 660px);
}}
.stMain {{
    background:
        radial-gradient(ellipse 70% 60% at 38% 46%, var(--tela-clara) 0%, transparent 70%),
        var(--tela);
}}
[data-testid="stMainBlockContainer"] {{ padding: .5rem 1.4rem .3rem 1.4rem; max-width: 100%; }}
section[data-testid="stSidebar"] {{ width: 288px !important; min-width: 288px !important; }}
[data-testid="stSidebarHeader"] {{ height: 2.4rem; padding-top: .4rem; padding-bottom: 0; }}
[data-testid="stSidebarUserContent"] {{ padding-top: 0; padding-bottom: .8rem; }}
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {{ gap: .55rem; }}
.marca-app {{
    font-family: Literata, Georgia, serif; color: var(--oro); font-weight: 600;
    font-size: 1.45rem; line-height: 1.2; margin: 0 0 .3rem 0;
}}
[data-testid="stSidebar"] h3 {{ font-size: 1rem; padding-top: .4rem; }}

/* Título de la historia sobre el libro */
.titulo-libro {{
    font-family: Literata, Georgia, serif; font-weight: 600; font-size: 1.45rem;
    color: var(--texto-tela); line-height: 1.2; margin: 0;
}}
.subtitulo-libro {{ color: var(--texto-tela-suave); font-size: .88rem; margin: .1rem 0 .15rem 0; }}

/* El libro: dos páginas de papel, el lomo al medio y el canto de las hojas abajo */
[class*="st-key-libro_"] {{
    background: var(--papel);
    border-radius: 3px;
    box-shadow:
        0 1px 0 var(--papel-borde), 0 3px 0 #D8CCAE, 0 5px 0 #CDBF9D,
        0 22px 44px rgba(0, 0, 0, .42);
}}
[class*="st-key-libro_"] [data-testid="stHorizontalBlock"] {{ gap: 0; }}
.st-key-pagina_izq, .st-key-pagina_der {{
    height: var(--alto-pagina) !important;
    max-height: var(--alto-pagina);
    flex: 0 0 auto !important;
    background: var(--papel);
    color: var(--tinta);
}}
.st-key-pagina_izq {{
    padding: 1.1rem 1.3rem 1.1rem 1.1rem;
    box-shadow: inset -26px 0 30px -24px rgba(70, 50, 20, .45);
    transform-origin: right center;
    justify-content: center;
    overflow: hidden;
}}
.st-key-pagina_der {{
    padding: 1.4rem 1.7rem 1rem 1.9rem;
    box-shadow: inset 26px 0 30px -24px rgba(70, 50, 20, .45);
    transform-origin: left center;
    overflow-y: auto;
}}
.st-key-pagina_izq [data-testid="stImage"] img {{
    max-height: calc(var(--alto-pagina) - 2.4rem);
    width: 100%;
    object-fit: contain;
    border-radius: 2px;
    box-shadow: 0 0 0 1px rgba(60, 45, 20, .18);
}}

/* Texto de la escena: Literata, capitular dorada */
.escena-fase {{
    font-family: Literata, Georgia, serif; font-style: italic; color: var(--oro-sobre-papel);
    font-size: 1.05rem; margin: 0;
}}
.escena-numero {{ color: var(--tinta-suave); font-size: .8rem; margin: 0 0 .7rem 0; }}
.escena-texto {{
    font-family: Literata, Georgia, serif; font-size: clamp(.9rem, 1.7vh, 1.05rem);
    line-height: 1.62; color: var(--tinta); hyphens: auto;
}}
.escena-texto p {{ margin: 0 0 .6em 0; color: var(--tinta); }}
.escena-texto p:first-child::first-letter {{
    float: left; font-size: 3.15em; line-height: .86; font-weight: 600;
    padding: .06em .09em 0 0; color: var(--oro-sobre-papel);
}}
.folio {{
    text-align: center; color: var(--tinta-suave); font-family: Literata, Georgia, serif;
    font-size: .8rem; margin: .4rem 0 0 0;
}}

/* Portada (página 0) y páginas en espera */
.lamina {{
    min-height: calc(var(--alto-pagina) - 2.2rem);
    background: var(--tela); border-radius: 2px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    text-align: center; padding: 2rem;
    box-shadow: inset 0 0 0 7px var(--tela), inset 0 0 0 8px var(--oro),
                inset 0 0 0 12px var(--tela), inset 0 0 0 13px rgba(210, 174, 91, .55);
}}
.lamina h2 {{
    font-family: Literata, Georgia, serif; color: var(--oro); font-weight: 600;
    font-size: clamp(1.3rem, 3.4vh, 2.1rem); line-height: 1.2; margin: 0 0 .7rem 0; padding: 0;
}}
.lamina p {{ color: var(--texto-tela-suave); font-size: .92rem; margin: 0; }}
.lamina p.idea {{
    font-family: Literata, Georgia, serif; font-style: italic; color: var(--texto-tela);
}}
.espera {{
    min-height: calc(var(--alto-pagina) - 6rem);
    border: 1px dashed #CDBF9D; border-radius: 2px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    text-align: center; padding: 1.5rem; color: var(--tinta-suave); gap: .4rem;
}}
.espera b {{ color: var(--tinta); font-family: Literata, Georgia, serif; font-weight: 600; }}
.espera p {{ color: var(--tinta-suave); margin: 0; font-size: .9rem; }}
.indice-titulo {{
    font-family: Literata, Georgia, serif; font-style: italic; color: var(--oro-sobre-papel);
    font-size: 1.15rem; margin: 0 0 .5rem 0;
}}
ol.indice {{ list-style: none; padding: 0; margin: 0; counter-reset: escena; }}
ol.indice li {{
    counter-increment: escena; display: grid; grid-template-columns: 1.5rem 1fr auto;
    gap: .2rem .5rem; padding: .42rem 0; border-bottom: 1px solid #EAE1CB;
    font-size: .86rem; line-height: 1.35; color: var(--tinta);
}}
ol.indice li::before {{
    content: counter(escena); font-family: Literata, Georgia, serif; font-weight: 600;
    color: var(--oro-sobre-papel); font-size: 1.05rem;
}}
ol.indice .fase {{
    font-family: Literata, Georgia, serif; font-style: italic; color: var(--tinta);
}}
ol.indice .resumen {{ color: var(--tinta-suave); display: block; }}
ol.indice .marca {{ color: var(--tinta-suave); font-size: .76rem; white-space: nowrap; }}
ol.indice .marca.lista {{ color: #3F6B45; }}
ol.indice .marca.curso {{ color: var(--oro-sobre-papel); font-weight: 700; }}
.instrucciones p {{
    font-family: Literata, Georgia, serif; font-size: .98rem; line-height: 1.6;
    color: var(--tinta); margin: 0 0 .7em 0;
}}

/* Barra de navegación bajo el libro */
.st-key-navegacion {{ margin-top: .6rem; }}
.st-key-navegacion [data-testid="stAudio"] {{ flex: 1 1 220px; min-width: 200px; }}

/* Panel derecho: detalles técnicos con scroll propio */
.st-key-panel {{
    max-height: calc(100vh - 1.4rem);
    overflow-y: auto;
    background: rgba(10, 30, 30, .3);
    border-left: 1px solid rgba(210, 174, 91, .3);
    padding: .2rem .9rem .8rem .9rem;
    border-radius: 0 4px 4px 0;
}}
.st-key-panel h3 {{
    font-family: Literata, Georgia, serif; font-weight: 600; color: var(--oro);
    font-size: 1.02rem; margin: .6rem 0 .25rem 0; padding: 0;
}}
dl.datos {{ margin: 0; padding: 0; }}
dl.datos dt {{ color: var(--texto-tela-suave); font-size: .76rem; margin: .45rem 0 0 0; }}
dl.datos dd {{
    margin: 0; padding: 0; color: var(--texto-tela); font-size: .86rem; line-height: 1.35;
    overflow-wrap: anywhere;
}}
.panel-nota {{ color: var(--texto-tela-suave); font-size: .78rem; margin: .3rem 0 0 0; }}
ul.avisos {{ margin: 0; padding-left: 1.1rem; }}
.prompt {{
    font-size: .8rem; line-height: 1.4; color: var(--texto-tela); margin: .15rem 0 .4rem 0;
    padding: .45rem .55rem; background: rgba(0, 0, 0, .18); border-radius: 4px;
}}

@media (prefers-reduced-motion: reduce) {{
    [class*="st-key-libro_"] * {{ animation: none !important; }}
}}
{giros}
</style>
"""


st.html(_css())


# ---------------------------------------------------------------------------------------
# Estado de la sesión
# ---------------------------------------------------------------------------------------
def _estado() -> Any:
    estado = st.session_state
    estado.setdefault("historia", None)  # carpeta de la historia abierta (str)
    estado.setdefault("escena", 0)  # 0 = portada e índice; 1..5 = escenas
    estado.setdefault("sentido", "adelante")
    estado.setdefault("generacion", None)  # GeneracionEnCurso
    estado.setdefault("seguir_avance", True)  # pasar sola de la portada a la escena 1
    estado.setdefault("autonarrar", True)
    return estado


def _configuracion(perfil: str) -> dict[str, Any]:
    perfil = perfil if perfil in ui_logica.PERFILES else "rapido"
    return config.load_config(perfil).model_dump(mode="json")


def _pipeline(perfil: str) -> Pipeline:
    cfg = config.load_config(perfil if perfil in ui_logica.PERFILES else "rapido")
    if MODO_SIMULADO:
        from storybook.mock import dependencias_simuladas

        return Pipeline(cfg, dependencias_simuladas())
    return Pipeline(cfg)


def _ir_a(numero: int) -> None:
    estado = _estado()
    numero = max(0, min(NUM_ESCENAS, numero))
    estado.sentido = "adelante" if numero >= estado.escena else "atras"
    estado.escena = numero
    estado.seguir_avance = False


def _abrir(carpeta: Path) -> None:
    estado = _estado()
    estado.historia = str(carpeta)
    estado.generacion = None
    estado.escena = 1
    estado.sentido = "adelante"


def _iniciar(idea: str, genero: str, otro: str | None, perfil: str) -> None:
    estado = _estado()
    pipeline = _pipeline(perfil)
    generar = functools.partial(pipeline.generar_por_escenas, idea, genero, otro)
    estado.generacion = GeneracionEnCurso(generar, perfil=perfil, idea=idea).iniciar()
    estado.historia = None
    estado.escena = 0
    estado.sentido = "adelante"
    estado.seguir_avance = True


# ---------------------------------------------------------------------------------------
# Barra lateral: nueva historia e historias guardadas
# ---------------------------------------------------------------------------------------
def barra_lateral(generando: bool) -> None:
    with st.sidebar:
        st.html("<p class='marca-app'>StoryBook IA</p>")
        if MODO_SIMULADO:
            st.warning("Modo simulado: sin GPU ni modelos. La historia es siempre la de ejemplo.")
        if audio_generativo_desactivado():
            st.warning(
                "Demostración de respaldo: el sonido generativo está desactivado. Los ambientes "
                "se crean con la síntesis procedural."
            )

        with st.form("nueva_historia", border=False):
            idea = st.text_area(
                "Idea",
                placeholder="Ej.: Un faro abandonado que se enciende solo cada noche",
                max_chars=500,
                height=84,
            )
            generos = ui_logica.opciones_genero()
            genero = st.selectbox(
                "Género", [g for g, _ in generos], format_func=dict(generos).__getitem__
            )
            genero_otro = st.text_input(
                "Si elegiste «Otro», ¿cuál?", max_chars=40, placeholder="Ej.: fábula"
            )
            perfil = st.radio(
                "Perfil", list(ui_logica.PERFILES), format_func=ui_logica.PERFILES.__getitem__
            )
            enviar = st.form_submit_button(
                "Generar historia", type="primary", disabled=generando, width="stretch"
            )
        if enviar:
            otro = genero_otro if genero == Genero.OTRO.value else None
            try:
                validar_entrada(idea, genero, otro)
            except InputValidationError as exc:
                st.error(str(exc))
            else:
                if CANDADO_GPU.locked():
                    st.error("Ya se está generando una historia en este equipo.")
                else:
                    _iniciar(idea, genero, otro, perfil)
                    st.rerun()

        st.subheader("Historias guardadas")
        entradas = listar_historias()
        if not entradas:
            st.caption("Aún no hay historias.")
            return
        elegida = st.selectbox(
            "Abrir", entradas, format_func=ui_logica.etiqueta_historia, label_visibility="collapsed"
        )
        if st.button("Abrir historia", disabled=generando, width="stretch") and elegida:
            _abrir(elegida.carpeta)
            st.rerun()


# ---------------------------------------------------------------------------------------
# El libro
# ---------------------------------------------------------------------------------------
def _e(texto: Any) -> str:
    return html.escape(str(texto))


def _parrafos(texto: str) -> str:
    partes = [p.strip() for p in texto.split("\n") if p.strip()]
    return "".join(f"<p>{_e(p)}</p>" for p in partes)


def _fase(numero: int) -> str:
    return ui_logica.fase_legible(ui_logica.FASE_POR_ESCENA[numero])


def _indice(vista: ui_logica.VistaLibro, en_vivo: Instantanea | None) -> str:
    filas = []
    for numero in range(1, NUM_ESCENAS + 1):
        resumen = vista.resumenes[numero - 1] if len(vista.resumenes) >= numero else ""
        situacion = vista.estado(numero)
        marca, clase = "", ""
        if situacion == "lista":
            lista_en = vista.paginas[numero].lista_en_s
            if lista_en is not None:
                marca, clase = f"lista a los {ui_logica.segundos_legibles(lista_en)}", "lista"
        elif situacion == "en_curso":
            marca, clase = "en curso", "curso"
        elif en_vivo is not None:
            marca = "pendiente"
        filas.append(
            f"<li><span><span class='fase'>{_e(_fase(numero))}</span>"
            f"<span class='resumen'>{_e(resumen)}</span></span>"
            f"<span class='marca {clase}'>{_e(marca)}</span></li>"
        )
    return f"<p class='indice-titulo'>Índice</p><ol class='indice'>{''.join(filas)}</ol>"


def _pagina_izquierda(
    vista: ui_logica.VistaLibro, numero: int, en_vivo: Instantanea | None
) -> None:
    pagina = vista.paginas.get(numero)
    if numero == 0:
        if vista.titulo:
            cuerpo = f"<h2>{_e(vista.titulo)}</h2><p>{_e(ui_logica.subtitulo(vista))}</p>"
        elif en_vivo is not None:
            cuerpo = f"<h2>Una historia nueva</h2><p class='idea'>«{_e(en_vivo.idea)}»</p>"
        else:
            cuerpo = "<h2>StoryBook IA</h2><p>Cuentos ilustrados y narrados en este equipo</p>"
        st.html(f"<div class='lamina'>{cuerpo}</div>")
    elif pagina is not None and pagina.archivos.imagen is not None:
        st.image(str(pagina.archivos.imagen), width="stretch")
    elif pagina is not None:
        st.html("<div class='espera'><b>Sin ilustración</b></div>")
    else:
        mensaje = en_vivo.mensaje if en_vivo is not None else ""
        st.html(f"<div class='espera'><b>Escena {numero}</b><p>{_e(mensaje)}</p></div>")


def _pagina_derecha(vista: ui_logica.VistaLibro, numero: int, en_vivo: Instantanea | None) -> None:
    if numero == 0:
        if vista.resumenes:
            st.html(_indice(vista, en_vivo))
        elif en_vivo is not None:
            st.html(
                "<div class='espera'><b>Planeando la historia</b>"
                "<p>Primero se escriben el título, los personajes y el resumen de las cinco "
                "escenas.</p></div>"
            )
        else:
            st.html(
                "<div class='instrucciones'><p class='indice-titulo'>Cómo empezar</p>"
                "<p>Escribe una idea en el panel de la izquierda, elige el género y presiona "
                "<b>Generar historia</b>.</p>"
                "<p>La primera escena aparece en cuanto tiene texto, ilustración, narración y "
                "ambiente sonoro; las demás se agregan mientras la lees.</p>"
                "<p>También puedes abrir una historia guardada.</p></div>"
            )
        return
    pagina = vista.paginas.get(numero)
    encabezado = (
        f"<p class='escena-fase'>{_e(_fase(numero))}</p>"
        f"<p class='escena-numero'>Escena {numero} de {NUM_ESCENAS}</p>"
    )
    if pagina is None:
        resumen = vista.resumenes[numero - 1] if len(vista.resumenes) >= numero else ""
        st.html(
            f"{encabezado}<div class='espera'><b>Se está escribiendo</b><p>{_e(resumen)}</p></div>"
        )
        return
    st.html(
        f"{encabezado}<div class='escena-texto' lang='es'>{_parrafos(pagina.texto)}</div>"
        f"<p class='folio'>{numero}</p>"
    )


def _navegacion(vista: ui_logica.VistaLibro, numero: int) -> None:
    estado = _estado()
    with st.container(key="navegacion", horizontal=True, vertical_alignment="center", gap="small"):
        st.button(
            "Anterior",
            icon=":material/chevron_left:",
            disabled=numero == 0,
            shortcut="Left",
            key="nav_anterior",
            on_click=_ir_a,
            args=(numero - 1,),
        )
        st.button(
            "Índice",
            key="nav_0",
            type="primary" if numero == 0 else "secondary",
            on_click=_ir_a,
            args=(0,),
        )
        for n in range(1, NUM_ESCENAS + 1):
            st.button(
                str(n),
                key=f"nav_{n}",
                type="primary" if n == numero else "secondary",
                disabled=not vista.navegable(n),
                icon=":material/hourglass_top:" if vista.estado(n) == "en_curso" else None,
                help=_fase(n),
                on_click=_ir_a,
                args=(n,),
            )
        siguiente = numero + 1
        st.button(
            "Siguiente",
            icon=":material/chevron_right:",
            icon_position="right",
            disabled=siguiente > NUM_ESCENAS or not vista.navegable(siguiente),
            shortcut="Right",
            key="nav_siguiente",
            on_click=_ir_a,
            args=(siguiente,),
        )
        pagina = vista.paginas.get(numero)
        audio = (pagina.archivos.mezcla or pagina.archivos.voz) if pagina else None
        if audio is not None:
            formato = "audio/ogg" if audio.suffix == ".ogg" else "audio/wav"
            st.audio(str(audio), format=formato, autoplay=bool(estado.autonarrar))


def libro(vista: ui_logica.VistaLibro, en_vivo: Instantanea | None) -> None:
    estado = _estado()
    numero = max(0, min(NUM_ESCENAS, int(estado.escena)))
    if numero and not vista.navegable(numero):
        numero = 0
    columna_libro, columna_panel = st.columns([3.15, 1.0], gap="medium")
    with columna_libro:
        titulo = vista.titulo or ("Generando una historia" if en_vivo else "StoryBook IA")
        subtitulo = ui_logica.subtitulo(vista) or ui_logica.ETIQUETA_IA
        st.html(
            f"<p class='titulo-libro'>{_e(titulo)}</p>"
            f"<p class='subtitulo-libro'>{_e(subtitulo)}</p>"
        )
        with st.container(key=f"libro_{numero}_{estado.sentido}"):
            izquierda, derecha = st.columns([1.22, 1.0], gap=None)
            with izquierda, st.container(key="pagina_izq"):
                _pagina_izquierda(vista, numero, en_vivo)
            with derecha, st.container(key="pagina_der"):
                _pagina_derecha(vista, numero, en_vivo)
        _navegacion(vista, numero)
    with columna_panel, st.container(key="panel"):
        panel(vista, numero, en_vivo)


# ---------------------------------------------------------------------------------------
# Panel derecho: detalles técnicos
# ---------------------------------------------------------------------------------------
def _datos(filas: list[tuple[str, str]]) -> None:
    if filas:
        cuerpo = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in filas)
        st.html(f"<dl class='datos'>{cuerpo}</dl>")


def _pista(etiqueta: str, ruta: Path | None) -> None:
    if ruta is not None:
        st.caption(etiqueta)
        st.audio(str(ruta), format="audio/ogg" if ruta.suffix == ".ogg" else "audio/wav")


def panel(vista: ui_logica.VistaLibro, numero: int, en_vivo: Instantanea | None) -> None:
    if en_vivo is not None and not en_vivo.terminada:
        st.html("<h3>Generando</h3>")
        st.progress(min(max(en_vivo.avance, 0.0), 1.0), text=en_vivo.mensaje)
        st.html(
            f"<p class='panel-nota'>{len(en_vivo.listas)} de {NUM_ESCENAS} escenas listas, "
            f"{ui_logica.segundos_legibles(en_vivo.transcurrido_s)} desde el inicio.</p>"
        )
    if en_vivo is not None and en_vivo.error:
        st.error(en_vivo.error)

    pagina = vista.paginas.get(numero)
    if pagina is not None:
        st.html(f"<h3>Escena {numero}</h3>")
        _datos(ui_logica.filas_escena(pagina.detalles, vista.personajes))
        prompts = ui_logica.prompts_escena(pagina.detalles)
        if prompts:
            with st.expander("Prompts usados"):
                for etiqueta, texto in prompts.items():
                    st.html(
                        f"<p class='panel-nota'>{_e(etiqueta)}</p>"
                        f"<p class='prompt' lang='en'>{_e(texto)}</p>"
                    )
        with st.expander("Pistas por separado"):
            _pista("Narración", pagina.archivos.voz)
            _pista("Ambiente sonoro", pagina.archivos.ambiente)
        _regenerar(vista, numero, en_vivo)

    st.html("<h3>Historia</h3>")
    _datos(ui_logica.filas_historia(vista))
    avisos = ui_logica.resumen_fallbacks(vista.manifest) if vista.manifest else []
    if avisos:
        st.html("<h3>Alternativas automáticas</h3>")
        items = "".join(f"<li class='panel-nota'>{_e(a)}</li>" for a in avisos)
        st.html(f"<ul class='avisos'>{items}</ul>")
    st.toggle("Narrar al pasar la página", key="autonarrar")
    st.html(f"<p class='panel-nota'>{_e(ui_logica.ETIQUETA_IA)}</p>")
    if vista.carpeta is not None:
        st.html(f"<p class='panel-nota'>Carpeta: {_e(vista.carpeta.name)}</p>")


def _regenerar(vista: ui_logica.VistaLibro, numero: int, en_vivo: Instantanea | None) -> None:
    carpeta = vista.carpeta
    if en_vivo is not None or carpeta is None or config.SAMPLES_DIR in carpeta.parents:
        return
    if not st.button("Regenerar ilustración y ambiente", width="stretch"):
        return
    if not CANDADO_GPU.acquire(blocking=False):
        st.warning("La GPU está ocupada con otra historia. Inténtalo cuando termine.")
        return
    try:
        with st.status(f"Regenerando la escena {numero}", expanded=True) as estado_ui:
            barra = st.progress(0.0)

            def progreso(_etapa: str, avance: float, mensaje: str) -> None:
                barra.progress(min(max(avance, 0.0), 1.0), text=mensaje)

            try:
                _pipeline(vista.perfil).regenerar_escena(carpeta, numero, progreso)
            except PipelineError as exc:
                estado_ui.update(label="No se pudo regenerar", state="error")
                st.error(str(exc))
                return
            estado_ui.update(label=f"Escena {numero} regenerada", state="complete")
    finally:
        CANDADO_GPU.release()
    st.rerun()


# ---------------------------------------------------------------------------------------
# Vistas (cada una es un fragmento: hojear no vuelve a dibujar la barra lateral)
# ---------------------------------------------------------------------------------------
def _vista_generacion() -> None:
    estado = _estado()
    generacion: GeneracionEnCurso | None = estado.generacion
    if generacion is None:
        st.rerun(scope="app")
        return
    instantanea = generacion.instantanea()
    if instantanea.terminada and not instantanea.error and instantanea.carpeta is not None:
        # Terminó: queda abierta como historia guardada, en la misma escena.
        estado.historia = str(instantanea.carpeta)
        estado.generacion = None
        st.rerun(scope="app")
        return
    vista = ui_logica.vista_en_vivo(instantanea, _configuracion(instantanea.perfil))
    # Mientras el usuario no hojee, la portada pasa sola a la escena 1 cuando está lista.
    if estado.seguir_avance and estado.escena == 0 and 1 in vista.paginas:
        estado.escena, estado.sentido, estado.seguir_avance = 1, "adelante", False
    libro(vista, instantanea)
    if instantanea.terminada:
        st.rerun(scope="app")  # terminó con error: se deja de consultar


vista_en_curso = st.fragment(run_every=CONSULTA_S)(_vista_generacion)


@st.fragment
def vista_con_error(generacion: GeneracionEnCurso) -> None:
    instantanea = generacion.instantanea()
    libro(ui_logica.vista_en_vivo(instantanea, _configuracion(instantanea.perfil)), instantanea)


@st.fragment
def vista_guardada(carpeta: str) -> None:
    try:
        historia = cargar_historia(Path(carpeta))
    except Exception as exc:  # carpeta borrada o Bible inválida
        st.error(f"No se pudo abrir la historia: {exc}")
        _estado().historia = None
        return
    libro(ui_logica.vista_de_historia(historia), None)


@st.fragment
def vista_inicial() -> None:
    vista = ui_logica.VistaLibro(
        titulo="",
        genero="",
        tono="",
        perfil="rapido",
        paginas={},
        configuracion=_configuracion("rapido"),
    )
    libro(vista, None)


# ---------------------------------------------------------------------------------------
estado = _estado()
generacion_actual: GeneracionEnCurso | None = estado.generacion
en_marcha = generacion_actual is not None and not generacion_actual.instantanea().terminada
barra_lateral(en_marcha)
if generacion_actual is not None and en_marcha:
    vista_en_curso()
elif generacion_actual is not None:
    vista_con_error(generacion_actual)
elif estado.historia:
    vista_guardada(estado.historia)
else:
    vista_inicial()
