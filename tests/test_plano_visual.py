"""El ilustrador y la mejor de 2 versiones (17 nov: "faltan o sobran personajes").

Con la idea "un perro rodeado de gatos", SDXL dibujaba a veces un solo gato o dos perros.
Ahora el LLM describe aparte qué se ve en cada imagen (``PlanoVisual``), el prompt se arma
con eso y, de dos versiones de cada escena, OpenCLIP elige la que mejor muestra a todos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from storybook import config, ui_logica
from storybook.config import ConsistencyConfig, load_config
from storybook.image import generator as generador_mod
from storybook.image.generator import (
    CARPETA_VERSIONES,
    FALLBACK_SIN_ELECCION,
    GeneradorImagenes,
    nombre_archivo_escena,
)
from storybook.image.prompt_builder import (
    NEGATIVO_CLONES,
    construir_prompt,
    singular_ingles,
)
from storybook.image.seleccion import elegir, puntuar, seeds_candidatos
from storybook.schemas import (
    Escena,
    PlanHistoria,
    PlanoVisual,
    StoryBible,
    derivar_seed,
    validar_entrada,
)
from storybook.story.planner import AVISO_PLANO, Planificador, ajustar_plano
from storybook.story.prompts import mensajes_plano_visual
from tests.fake_llm import FakeLLM
from tests.test_image_generator import FakeBackend, FakeOOM
from tests.test_prompt_builder import _perro_y_gatos

GATOS = {"frase": "surrounded by many cats", "especie": "cat", "plural": "cats"}
CAMPOS_PLAN = ("titulo", "genero", "tono", "estilo_visual", "escenario")


def _plano(principal: str, *acompanantes: tuple[str, str], **campos: str) -> dict[str, Any]:
    return {
        "principal": principal,
        "acompanantes": [{"quien": q, "cantidad": c} for q, c in acompanantes],
        "accion": campos.get("accion", "looks up at the glowing rooftops"),
        "lugar": campos.get("lugar", "a narrow street at dusk"),
        "plano": campos.get("plano", "wide shot"),
    }


def _bible(bible_dict: dict, planos: dict[int, dict[str, Any]], grupo: dict | None = GATOS):
    datos = _perro_y_gatos(bible_dict, grupo or GATOS)
    if grupo is None:
        datos["grupos"] = []
    for numero, plano in planos.items():
        datos["escenas"][numero - 1]["plano_visual"] = plano
    return StoryBible.model_validate(datos)


# ---------------------------------------------------------------------------------------
# El plano visual (esquema y ajuste al reparto de la escena)
# ---------------------------------------------------------------------------------------
def test_el_plano_se_limpia_y_se_acorta() -> None:
    plano = PlanoVisual.model_validate(
        {
            "principal": "Martillo",
            "acompanantes": [{"quien": "<Cats>", "cantidad": "many"}],
            "accion": "<looks> up at the glowing rooftops while the rain falls softly on the old "
            "tiles of the sleeping city and the lamps flicker.",
            "lugar": "a narrow street",
        }
    )
    assert plano.principal == "martillo" and plano.acompanantes[0].quien == "cats"
    assert plano.accion.startswith("looks up") and len(plano.accion.split()) <= 18
    assert plano.plano == "medium shot"
    with pytest.raises(ValueError, match="inglés"):
        PlanoVisual.model_validate(
            {"principal": "martillo", "accion": "mira los tejados de la ciudad", "lugar": "calle"}
        )


def test_ajustar_plano_deja_solo_a_quien_esta_en_la_escena(bible_dict: dict) -> None:
    bible = _bible(bible_dict, {})
    plan = PlanHistoria.model_validate(
        {
            **{k: bible_dict[k] for k in CAMPOS_PLAN},
            "personajes": [json.loads(p.model_dump_json()) for p in bible.personajes],
            "plan_escenas": [
                {"numero": e.numero, "fase": e.fase, "resumen": e.resumen,
                 "personajes_presentes": list(e.personajes_presentes)}
                for e in bible.escenas
            ],
        }
    )  # fmt: skip
    solo_perro = bible.escena(4)  # solo martillo
    plano = PlanoVisual.model_validate(
        _plano("razor", ("razor", "one"), ("martillo", "one"), plano="close-up")
    )
    ajustado = ajustar_plano(plano, solo_perro, plan)
    # razor no está: el principal pasa a ser el protagonista y no queda repetido.
    assert ajustado.principal == "martillo" and ajustado.acompanantes == []
    # El nombre en vez del id se corrige; una especie sin nombre se deja solo si la escena
    # la nombra (18 nov: el ilustrador ponía gatos en la historia de un dragón).
    plano = PlanoVisual.model_validate(_plano("martillo", ("Razor", "one"), ("birds", "two")))
    escena = bible.escena(1)
    ajustado = ajustar_plano(plano, escena, plan)
    assert [(f.quien, f.cantidad) for f in ajustado.acompanantes] == [("razor", "one")]
    con_pajaros = escena.model_copy(
        update={"texto_narrativo": escena.texto_narrativo + " Dos pájaros cruzan el cielo."}
    )
    ajustado = ajustar_plano(plano, con_pajaros, plan)
    assert [(f.quien, f.cantidad) for f in ajustado.acompanantes] == [
        ("razor", "one"),
        ("birds", "two"),
    ]
    en_ingles = escena.model_copy(update={"prompt_imagen": "Martillo watches two birds"})
    assert len(ajustar_plano(plano, en_ingles, plan).acompanantes) == 2


def test_mensajes_del_ilustrador(bible_dict: dict) -> None:
    datos = _perro_y_gatos(bible_dict, GATOS)
    plan = PlanHistoria.model_validate(
        {
            **{k: datos[k] for k in CAMPOS_PLAN},
            "personajes": datos["personajes"],
            "plan_escenas": [
                {"numero": e["numero"], "fase": e["fase"], "resumen": e["resumen"],
                 "personajes_presentes": e["personajes_presentes"]}
                for e in datos["escenas"]
            ],
            "grupos": [GATOS],
        }
    )  # fmt: skip
    escena = Escena.model_validate(datos["escenas"][0])
    sistema, usuario = mensajes_plano_visual(plan, escena)
    assert "director de arte" in sistema["content"]
    assert "- martillo: Martillo (dog age 3)" in usuario["content"]
    assert "- razor: Razor (cat age 4)" in usuario["content"]
    assert '"surrounded by many cats"' in usuario["content"] and '"many"' in usuario["content"]


def test_el_planificador_agrega_el_plano_a_la_escena(bible_dict: dict) -> None:
    from tests.test_reparto import _plan

    bible = StoryBible.model_validate(bible_dict)
    escena_1 = json.loads(bible.escena(1).model_dump_json())
    llm = (
        FakeLLM()
        .encolar("PlanHistoria", _plan(bible_dict, list(bible.personajes)))
        .encolar("Escena", escena_1, escena_1)
        .encolar("PlanoVisual", _plano("lucia", ("abuelo_tomas", "one")), RuntimeError("json"))
    )
    cfg = config.load_config("rapido").llm
    assert cfg.plano_visual
    planificador = Planificador(llm, cfg)
    plan, _ = planificador.planificar(validar_entrada("Un faro que se enciende solo", "misterio"))
    escena, _ = planificador.escribir_escena(plan, 1, [], "misterio")
    assert escena.plano_visual is not None and escena.plano_visual.principal == "lucia"
    llamada = llm.llamadas_de(PlanoVisual)[0]
    assert llamada["temperature"] == 0.3 and "Lucía" in llamada["messages"][-1]["content"]
    # Si el ilustrador falla, la escena sigue con su prompt_imagen y queda un aviso.
    escena, _ = planificador.escribir_escena(plan, 1, [], "misterio")
    assert escena.plano_visual is None
    assert planificador.avisos == [f"{AVISO_PLANO}:1"]
    # Los experimentos (batería 6.2) no lo usan.
    assert not config.load_config("experiments/c3_ipadapter").llm.plano_visual


# ---------------------------------------------------------------------------------------
# El prompt a partir del plano
# ---------------------------------------------------------------------------------------
def test_el_perro_rodeado_de_gatos_se_arma_desde_el_plano(bible_dict: dict) -> None:
    plano = _plano("martillo", ("cats", "many"), accion="Martillo looks up at the rooftops")
    bible = _bible(bible_dict, {1: plano})
    p = construir_prompt(bible, 1, personajes="foco", orden="accion_primero")
    # Quién (y cuántos) primero; el nombre ya no se repite en la acción.
    assert p.prompt.startswith(
        "wide shot, a dog surrounded by many cats, looks up at the rooftops, a narrow street"
    )
    assert p.ip_factor == 0.0  # la referencia del protagonista es un perro solo
    assert "torn ear" not in p.prompt and "silver fur" in p.prompt  # descriptor acortado
    assert "two dogs" in p.negative_prompt and "clone" not in p.negative_prompt
    assert "cats" not in p.negative_prompt
    assert p.verificar == ["a dog", "many cats"] and p.evitar == ["two dogs"]
    assert p.foco == "martillo" and p.a_dict()["verificar"] == p.verificar


def test_solo_o_acompanado_cambia_la_referencia_y_el_negative(bible_dict: dict) -> None:
    bible = _bible(
        bible_dict,
        {
            4: _plano("martillo", accion="sleeps under a bridge", plano="close-up"),
            2: _plano("razor", ("martillo", "one"), accion="the cat stands on a bridge"),
            3: _plano("martillo", ("dog", "two"), accion="runs with his friends"),
        },
        grupo=None,
    )
    solo = construir_prompt(bible, 4, personajes="foco", orden="accion_primero")
    assert solo.prompt.startswith("close-up, a dog, sleeps under a bridge")
    assert solo.ip_factor == 1.0 and "torn ear" in solo.prompt
    assert NEGATIVO_CLONES in solo.negative_prompt and solo.verificar == ["a dog"]

    gato = construir_prompt(bible, 2, personajes="foco", orden="accion_primero")
    assert gato.prompt.startswith("wide shot, a cat, with a dog, stands on a bridge")
    assert gato.ip_factor == 0.0  # el principal no es el protagonista
    assert gato.verificar == ["a cat", "a dog"] and gato.evitar == ["two cats"]

    perros = construir_prompt(bible, 3, personajes="foco", orden="accion_primero")
    assert perros.prompt.startswith("wide shot, a dog, with two dogs, runs with his friends")
    assert perros.ip_factor == 0.6  # acompañado, pero de su especie: la referencia sirve
    assert "two dogs" not in perros.negative_prompt and perros.evitar == []


def test_dos_figuras_iguales_se_verifican_como_dos(bible_dict: dict) -> None:
    datos = json.loads(json.dumps(bible_dict))
    datos["personajes"][1]["descripcion_visual_fija"] = "girl age 9, short black hair"
    datos["escenas"][0]["plano_visual"] = _plano("lucia", ("abuelo_tomas", "one"))
    p = construir_prompt(StoryBible.model_validate(datos), 1, personajes="foco")
    assert "a girl, with a girl" in p.prompt
    assert p.verificar == ["two girls"] and p.evitar == [] and "clone" not in p.negative_prompt


def test_la_historia_de_los_gatos_del_13_nov(bible_dict: dict) -> None:
    """Escena 5 de "Un perro rodeado de gatos": Kael con Mira y Zorin (dos gatos)."""
    datos = _perro_y_gatos(bible_dict, GATOS)
    datos["personajes"].append(
        {**datos["personajes"][1], "id": "zorin", "nombre": "Zorin",
         "descripcion_visual_fija": "cat age 5 years, long fur, black coat with silver tips"}
    )  # fmt: skip
    datos["escenas"][4]["personajes_presentes"] = ["martillo", "razor", "zorin"]
    datos["escenas"][4]["plano_visual"] = _plano(
        "martillo", ("razor", "one"), ("zorin", "one"), accion="Martillo faces the city below"
    )
    p = construir_prompt(StoryBible.model_validate(datos), 5, personajes="foco")
    assert "a dog surrounded by many cats, with two cats, faces the city below" in p.prompt
    assert p.verificar == ["a dog", "two cats", "many cats"] and p.ip_factor == 0.0


def test_sin_plano_tambien_dice_que_debe_verse(bible_dict: dict) -> None:
    bible = _bible(bible_dict, {})
    uno = construir_prompt(bible, 1, personajes="foco", orden="accion_primero")
    assert uno.prompt.startswith("a dog surrounded by many cats")  # como el 13 nov
    assert uno.verificar == ["a dog", "many cats"] and uno.evitar == ["two dogs"]


@pytest.mark.parametrize(
    ("plural", "singular"),
    [("cats", "cat"), ("foxes", "fox"), ("wolves", "wolf"), ("butterflies", "butterfly"),
     ("horses", "horse"), ("fish", "fish"), ("cat", "cat")],
)  # fmt: skip
def test_singular_ingles(plural: str, singular: str) -> None:
    assert singular_ingles(plural) == singular


# ---------------------------------------------------------------------------------------
# La mejor de N versiones
# ---------------------------------------------------------------------------------------
def test_puntaje_premia_que_se_vean_todos() -> None:
    # Una versión con el perro muy claro pero sin gatos pierde frente a una con los dos.
    assert puntuar([0.30, 0.12]) < puntuar([0.26, 0.22])
    # "two dogs" más parecido que "a dog": castigo.
    assert puntuar([0.26, 0.22], [0.30]) < puntuar([0.26, 0.22], [0.20])
    assert seeds_candidatos(7, 1) == [7]
    tres = seeds_candidatos(7, 3)
    assert tres[0] == 7 and len(set(tres)) == 3 and tres[1] == derivar_seed(7, "candidato", 1)


class FakeEvaluador:
    """Similitud = rojo medio de la imagen (el FakePipe pinta cada llamada más roja)."""

    def __init__(self, fallar: bool = False) -> None:
        self.textos: list[list[str]] = []
        self.fallar = fallar

    def similitudes(self, imagenes: list[Image.Image], textos: list[str]) -> list[list[float]]:
        if self.fallar:
            raise RuntimeError("CLIP roto")
        self.textos.append(list(textos))
        return [[imagen.getpixel((0, 0))[0] / 255] * len(textos) for imagen in imagenes]


def test_elegir_con_un_evaluador() -> None:
    rojo, oscuro = Image.new("RGB", (8, 8), (200, 0, 0)), Image.new("RGB", (8, 8), (20, 0, 0))
    evaluador = FakeEvaluador()
    eleccion = elegir(evaluador, [oscuro, rojo], ["a dog", "many cats"], ["two dogs"])
    assert eleccion.elegida == 1
    assert evaluador.textos == [
        ["a picture of a dog", "a picture of many cats", "a picture of two dogs"]
    ]
    assert set(eleccion.detalle[0]["presencia"]) == {"a dog", "many cats"}


def _generador(backend: FakeBackend, evaluador: Any, candidatos: int = 2) -> GeneradorImagenes:
    base = load_config("default").image
    cfg = base.model_copy(update={"candidatos": candidatos})
    return GeneradorImagenes(cfg, ConsistencyConfig(), backend, evaluador=evaluador)


def test_se_queda_la_version_que_elige_clip(bible_dict: dict, tmp_path: Path) -> None:
    bible = _bible(bible_dict, {1: _plano("martillo", ("cats", "many"))})
    backend, evaluador = FakeBackend(), FakeEvaluador()
    etapa = _generador(backend, evaluador).generar(bible, tmp_path, numeros=[1])
    assert len(backend.llamadas) == 3  # character sheet + 2 versiones
    seed = etapa.bible.escena(1).seed_imagen
    assert [c["generator"] for c in backend.llamadas[1:]] == [
        ("gen", seed),
        ("gen", derivar_seed(seed, "candidato", 1)),
    ]
    r = etapa.imagenes[0]
    # La segunda llamada es más roja: CLIP falso la prefiere y queda como scene_1.png.
    assert Image.open(r.ruta).getpixel((0, 0)) == (60, 0, 0)
    assert r.seed == derivar_seed(seed, "candidato", 1) and r.seed_escena == seed
    assert [v["elegida"] for v in r.versiones] == [False, True]
    assert r.versiones[1]["puntaje"] > r.versiones[0]["puntaje"]
    assert (tmp_path / CARPETA_VERSIONES / "scene_1_v1.jpg").is_file()
    assert evaluador.textos[0][:2] == ["a picture of a dog", "a picture of many cats"]
    etapas = [m.etapa for m in etapa.metricas]
    assert "imagen_escena_1_v2" in etapas and "imagen_eleccion_1" in etapas
    assert etapa.fallbacks == [] and etapa.parametros["versiones_por_escena"] == 2
    assert r.a_dict()["versiones"] == r.versiones and r.a_dict()["seed_escena"] == seed


def test_si_clip_falla_queda_la_primera(bible_dict: dict, tmp_path: Path) -> None:
    bible = _bible(bible_dict, {})
    etapa = _generador(FakeBackend(), FakeEvaluador(fallar=True)).generar(
        bible, tmp_path, numeros=[1]
    )
    r = etapa.imagenes[0]
    assert Image.open(r.ruta).getpixel((0, 0)) == (40, 0, 0) and r.seed == r.seed_escena
    assert etapa.fallbacks == [f"{FALLBACK_SIN_ELECCION}:1"] and not r.respaldo


def test_si_openclip_no_carga_se_intenta_una_sola_vez(
    bible_dict: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import storybook.evaluation.clip_metrics as clip_metrics

    intentos: list[int] = []

    def sin_clip(*_: Any, **__: Any) -> None:
        intentos.append(1)
        raise ImportError("No module named 'open_clip'")

    monkeypatch.setattr(clip_metrics, "ClipScorer", sin_clip)
    bible = _bible(bible_dict, {})
    generador = _generador(FakeBackend(), None)
    etapa = generador.generar(bible, tmp_path, numeros=[1, 2])
    assert intentos == [1]
    assert etapa.fallbacks == [f"{FALLBACK_SIN_ELECCION}:1", f"{FALLBACK_SIN_ELECCION}:2"]
    for r in etapa.imagenes:  # las dos versiones quedan registradas; se usa la primera
        assert not r.respaldo and [v["elegida"] for v in r.versiones] == [True, False]
        assert "puntaje" not in r.versiones[0]
    texto = ui_logica.texto_versiones(etapa.imagenes[0].versiones)
    assert texto == "2, quedó la 1.ª (CLIP no disponible)"


def test_un_oom_en_la_segunda_version_deja_la_primera(bible_dict: dict, tmp_path: Path) -> None:
    oom = FakeOOM("CUDA out of memory")
    backend = FakeBackend(fallos={3: oom, 4: oom})  # 1 = sheet, 2 = versión 1
    etapa = _generador(backend, FakeEvaluador()).generar(_bible(bible_dict, {}), tmp_path, [1])
    r = etapa.imagenes[0]
    assert not r.respaldo and r.intentos == 3 and r.versiones == []
    assert r.ruta == tmp_path / nombre_archivo_escena(1)


def test_con_una_version_no_se_carga_clip(bible_dict: dict, tmp_path: Path) -> None:
    generador = _generador(FakeBackend(), None, candidatos=1)
    etapa = generador.generar(_bible(bible_dict, {}), tmp_path, numeros=[1])
    assert generador.evaluador() is None and etapa.fallbacks == []
    assert not (tmp_path / CARPETA_VERSIONES).exists()


def test_precarga_tambien_prepara_clip(tmp_path: Path) -> None:
    evaluador = FakeEvaluador()
    generador = _generador(FakeBackend(), evaluador)
    pipe, _ = generador.precargar().result(timeout=10)
    assert pipe is not None and generador.evaluador() is evaluador
    assert generador_mod.CARPETA_VERSIONES == "versiones"


# ---------------------------------------------------------------------------------------
# Panel técnico
# ---------------------------------------------------------------------------------------
def test_el_panel_muestra_que_debia_verse_y_la_version_elegida() -> None:
    detalles = {
        "imagen": {
            "seed": 9,
            "segundos": 22.4,
            "ip_escala": 0.0,
            "prompt": {"foco": "martillo", "verificar": ["a dog", "many cats"]},
            "versiones": [
                {"seed": 1, "puntaje": 0.25, "elegida": False},
                {"seed": 9, "puntaje": 0.271, "elegida": True},
            ],
        }
    }
    filas = dict(ui_logica.filas_escena(detalles, {"martillo": "Martillo"}))
    assert filas["Lo que debe verse"] == "a dog, many cats"
    assert filas["Versiones de la imagen"] == "2, se eligió la 2.ª (CLIP 0,271 frente a 0,250)"


def test_el_grupo_de_la_idea_cuenta_aunque_la_escena_no_lo_nombre(bible_dict: dict) -> None:
    datos = _perro_y_gatos(bible_dict, GATOS)
    plan = PlanHistoria.desde_bible(StoryBible.model_validate(datos))
    escena = Escena.model_validate(datos["escenas"][0])
    plano = PlanoVisual.model_validate(_plano("martillo", ("cats", "many"), ("owl", "one")))
    ajustado = ajustar_plano(plano, escena, plan)
    assert [f.quien for f in ajustado.acompanantes] == ["cats"]  # el búho no está en la escena


def test_las_instrucciones_del_ilustrador_no_traen_especies_de_ejemplo() -> None:
    from storybook.story.prompts import SISTEMA_PLANO_VISUAL

    assert '"cat"' not in SISTEMA_PLANO_VISUAL and '"bird"' not in SISTEMA_PLANO_VISUAL
    assert "No inventes" in SISTEMA_PLANO_VISUAL


def test_con_flux_el_prompt_lleva_mas_detalle(bible_dict: dict) -> None:
    """18 nov: con T5 (256 tokens) el principal lleva el descriptor completo y cada
    acompañante con nombre dos rasgos; con CLIP (77) se acortaba."""
    plano = _plano("martillo", ("razor", "one"), accion="Martillo looks up at the rooftops")
    bible = _bible(bible_dict, {2: plano}, grupo=None)
    corto = construir_prompt(bible, 2, personajes="foco", orden="accion_primero")
    largo = construir_prompt(
        bible, 2, personajes="foco", orden="accion_primero", max_tokens=254, encoder_largo=True
    )
    assert "with a cat," in corto.prompt and "torn ear" not in corto.prompt
    assert "with a cat (orange with red spots)" in largo.prompt and "torn ear" in largo.prompt
    assert largo.verificar == corto.verificar == ["a dog", "a cat"]
    assert not largo.truncado


def test_con_flux_la_tecnica_abre_el_prompt(bible_dict: dict) -> None:
    """20 nov: con todo el estilo al final, FLUX dibujó una escena como foto y no como
    acuarela. La técnica va primero (una sola vez); paleta e iluminación, al final."""
    plano = _plano("martillo", ("razor", "one"), accion="Martillo looks up at the rooftops")
    bible = _bible(bible_dict, {2: plano}, grupo=None)
    estilo = bible.estilo_visual
    largo = construir_prompt(
        bible, 2, personajes="foco", orden="accion_primero", max_tokens=254, encoder_largo=True
    )
    assert largo.prompt.startswith(f"{estilo.tecnica}, wide shot, a dog, with a cat (")
    assert largo.prompt.count(estilo.tecnica) == 1
    assert largo.prompt.endswith(estilo.iluminacion) and estilo.paleta in largo.prompt
    corto = construir_prompt(bible, 2, personajes="foco", orden="accion_primero")
    assert corto.prompt.startswith("wide shot, a dog") and estilo.tecnica in corto.prompt


def _nino_y_nina(bible_dict: dict, principal: str) -> StoryBible:
    datos = _perro_y_gatos(bible_dict, GATOS)
    datos["grupos"] = []
    datos["personajes"][0]["descripcion_visual_fija"] = f"{principal}, age 7, red hair, raincoat"
    datos["personajes"][1]["descripcion_visual_fija"] = "girl, age 8, black braids, green dress"
    datos["escenas"][1]["plano_visual"] = _plano(
        "martillo", ("razor", "one"), accion="runs toward the swings", lugar="a sunny park"
    )
    return StoryBible.model_validate(datos)


def test_un_child_con_una_nina_no_evita_dos_ninos(bible_dict: dict) -> None:
    """20 nov: con el principal 'child' y una niña al lado se evitaba "two children"
    (negative y elección de versión): justo lo que pedía la escena."""
    from storybook.image.prompt_builder import misma_familia

    generico = construir_prompt(
        _nino_y_nina(bible_dict, "child"), 2, personajes="foco", orden="accion_primero"
    )
    assert generico.evitar == [] and "children" not in generico.negative_prompt
    assert generico.verificar == ["a child", "a girl"]
    nino = construir_prompt(
        _nino_y_nina(bible_dict, "boy"), 2, personajes="foco", orden="accion_primero"
    )
    assert nino.evitar == ["two boys"] and "multiple boys" in nino.negative_prompt
    assert misma_familia("child", "girl") and misma_familia("person", "man")
    assert not misma_familia("boy", "girl") and not misma_familia("child", "dog")
    assert not misma_familia("person", "robot")
