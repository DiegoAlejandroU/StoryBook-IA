"""Plantillas de prompts para el LLM. Los límites numéricos vienen de ``schemas`` para que
prompt y validación nunca se desincronicen."""

from __future__ import annotations

import json

from storybook.schemas import (
    FASE_POR_NUMERO,
    MAX_PERSONAJES,
    MIN_ESCENAS_PROTAGONISTA,
    PALABRAS_MAX_ESCENA,
    PALABRAS_MAX_PROMPT_SONIDO,
    PALABRAS_MIN_ESCENA,
    TOKENS_MAX_DESCRIPTOR,
    TOKENS_MAX_ESTILO,
    TOKENS_MAX_PROMPT_IMAGEN,
    Contradiccion,
    Escena,
    EtiquetaSonido,
    Genero,
    PlanHistoria,
    StoryBible,
    StoryRequest,
)

# Margen para las comas: el esquema limita tokens (palabras + signos), el prompt habla de palabras.
# Con 0,75 el 4B se pasó del presupuesto en F1 (~28 tokens de 25): los modelos pequeños
# escriben algo más de lo que se les pide, así que se pide un 20 % menos.
_FACTOR_PALABRAS = 0.6

# Los modelos pequeños escriben menos de lo pedido: en F1, con "7 a 10 oraciones", la
# primera versión de cada escena tuvo 48-88 palabras (mínimo 90). Se pide más y se repite
# al final del mensaje de usuario, que es lo que el modelo tiene más presente.
LONGITUD_ESCENA = "de 10 a 12 oraciones completas (unas 120 palabras)"

# La primera frase del descriptor es el sujeto que usa prompt_builder al cambiar nombres por
# descripciones: debe decir quién es. En la prueba de 2.3 empezaba por "25 years old" (sin
# tipo de persona) y el prompt de la escena quedó "25 years old touching a switch".
# 13 nov: el ejemplo anterior ("woman, boy, old man, robot") era justo el reparto que el 4B
# inventó para "un grupo de amigos animales". Ahora el ejemplo no sugiere personajes.
ORDEN_DESCRIPTOR = (
    "primero quién es y su edad en una sola frase: el tipo en inglés (la especie si es un "
    'animal o la clase de persona si es humano), la palabra "age" y la edad, sin símbolos; '
    "luego pelaje o cabello, ropa o accesorio, un rasgo distintivo y complexión, como frases "
    'sueltas SIN etiquetas (nada de "age:" ni "hair:")'
)
# 18 nov: la regla solo hablaba de animales y el 4B puso animales en todo ("un niño en un
# parque" -> un zorrito). Ahora dice las tres situaciones.
REGLA_REPARTO = (
    "Los personajes son los que pide la idea: si nombra una persona (un niño, una chica, un "
    "piloto), el protagonista es esa persona; si habla de animales, TODOS son animales (nada "
    "de personas ni robots que la idea no mencione); si NO menciona animales, los personajes "
    "son personas, no animales. Cada persona o especie que nombra la idea aparece en el reparto."
)


def _palabras(tokens_max: int) -> int:
    return int(tokens_max * _FACTOR_PALABRAS)


REGLAS_GENERO: dict[Genero, str] = {
    Genero.TERROR: "Atmósfera inquietante y suspenso; sin gore ni violencia explícita.",
    Genero.FANTASIA: "Mundo con magia coherente: las reglas mágicas no cambian entre escenas.",
    Genero.MISTERIO: "Siembra pistas desde el inicio y resuélvelas en el desenlace.",
    Genero.AVENTURA: "Viaje con obstáculos crecientes y un objetivo claro.",
    Genero.CIENCIA_FICCION: "Tecnología plausible y consistente con el escenario.",
    Genero.INFANTIL: (
        "Para niños de 6 a 10 años: lenguaje sencillo, sin violencia ni miedo intenso, "
        "final esperanzador."
    ),
    Genero.OTRO: "Respeta las convenciones del género indicado por el usuario.",
}

SISTEMA_BIBLE = f"""Eres un guionista de cuentos ilustrados y diseñador de producción.
Produces una "Story Bible" en JSON que sigue EXACTAMENTE el esquema recibido.

Reglas obligatorias:
1. Exactamente 5 escenas con este arco: 1=inicio, 2=desarrollo, 3=desarrollo, 4=climax,
   5=desenlace.
2. titulo, tono, resúmenes y texto_narrativo SIEMPRE en español. texto_narrativo de
   {PALABRAS_MIN_ESCENA} a {PALABRAS_MAX_ESCENA} palabras por escena: escribe {LONGITUD_ESCENA};
   con menos de {PALABRAS_MIN_ESCENA} palabras se rechaza.
3. Entre 1 y {MAX_PERSONAJES} personajes; exactamente uno con rol "protagonista", presente en la
   escena 1 y en al menos {MIN_ESCENAS_PROTAGONISTA} escenas. Usa siempre el mismo nombre.
   {REGLA_REPARTO}
4. Los campos para el ilustrador y el sonidista van en INGLÉS, como frases breves separadas por
   comas (cada coma también consume espacio del modelo de imagen):
   - estilo_visual (tecnica + paleta + iluminacion): máximo {_palabras(TOKENS_MAX_ESTILO)} palabras
     en total.
   - descripcion_visual_fija: máximo {_palabras(TOKENS_MAX_DESCRIPTOR)} palabras, en este orden:
     {ORDEN_DESCRIPTOR}. No describas el estado de ánimo.
   - prompt_imagen: máximo {_palabras(TOKENS_MAX_PROMPT_IMAGEN)} palabras: UN sujeto principal
     (el protagonista si está en la escena, con su nombre exacto) haciendo la acción, la
     composición y el entorno; máximo 2 personajes, nombrados por su nombre. No repitas la
     descripción del personaje ni el estilo: se añaden automáticamente.
   - prompt_sonido: máximo {PALABRAS_MAX_PROMPT_SONIDO} palabras: un ambiente y 1-2 efectos.
     Sin voces ni música.
5. etiquetas_sonido: 1 a 3 valores de esta lista: {", ".join(e.value for e in EtiquetaSonido)}.
6. hechos_nuevos: hechos concretos que la escena establece. Las escenas posteriores no pueden
   contradecirlos (nombres, rasgos, objetos, lugares, relaciones).
7. El resumen de cada escena es una sola frase en español.
8. No incluyas texto fuera del JSON."""


def prompt_usuario_bible(solicitud: StoryRequest) -> str:
    regla = REGLAS_GENERO[solicitud.genero]
    return (
        f"Idea del usuario: {solicitud.idea}\n"
        f"Género: {solicitud.genero_efectivo}\n"
        f"Indicación de género: {regla}\n"
        "Genera la Story Bible completa."
    )


def mensajes_bible(solicitud: StoryRequest) -> list[dict[str, str]]:
    """Mensajes para la estrategia (a): una sola llamada que genera la Bible completa."""
    return [
        {"role": "system", "content": SISTEMA_BIBLE},
        {"role": "user", "content": prompt_usuario_bible(solicitud)},
    ]


def mensaje_reparacion(
    errores: list[str], objeto: str = "la Story Bible completa"
) -> dict[str, str]:
    """Mensaje que devuelve al modelo los errores de validación para que corrija."""
    lista = "\n".join(f"- {e}" for e in errores[:12])
    return {
        "role": "user",
        "content": (
            "El JSON anterior no pasó la validación. Corrige SOLO estos problemas y devuelve "
            f"{objeto}:\n{lista}\n"
            # En F1, al pedirle un campo en inglés, el 4B pasó TODO el plan al inglés.
            "No cambies lo que ya estaba bien: titulo, tono, resúmenes y texto_narrativo "
            "siguen en español; solo los campos para el ilustrador y el sonidista van en inglés."
        ),
    }


# ---------------------------------------------------------------------------------------
# Estrategia (b): plan + personajes primero, luego expansión escena por escena
# ---------------------------------------------------------------------------------------
SISTEMA_PLAN = f"""Eres un guionista de cuentos ilustrados y diseñador de producción.
Produces el PLAN de una historia en JSON que sigue EXACTAMENTE el esquema recibido.

Reglas obligatorias:
1. plan_escenas: exactamente 5 escenas con este arco: 1=inicio, 2=desarrollo,
   3=desarrollo, 4=climax, 5=desenlace. Cada resumen es una sola frase en español.
2. Entre 1 y {MAX_PERSONAJES} personajes; exactamente uno con rol "protagonista", presente en la
   escena 1 y en al menos {MIN_ESCENAS_PROTAGONISTA} escenas. Inventa nombres propios que encajen
   con esta historia. El id de cada personaje es su nombre en minúsculas, sin tildes y con "_"
   en lugar de espacios; usa exactamente esos ids en plan_escenas. {REGLA_REPARTO}
3. titulo, tono, escenario, resúmenes y canon_inicial en ESPAÑOL, aunque la idea sugiera
   otro idioma. tono: de 2 a 4 adjetivos.
4. estilo_visual (tecnica + paleta + iluminacion) en INGLÉS: máximo
   {_palabras(TOKENS_MAX_ESTILO)} palabras en total.
5. descripcion_visual_fija en INGLÉS: máximo {_palabras(TOKENS_MAX_DESCRIPTOR)} palabras, en este
   orden: {ORDEN_DESCRIPTOR}.
6. canon_inicial: hechos del mundo que se mantienen durante toda la historia.
7. No incluyas texto fuera del JSON."""

SISTEMA_ESCENA = f"""Eres un guionista de cuentos ilustrados. Escribes UNA escena en JSON que
sigue EXACTAMENTE el esquema recibido, a partir del plan aprobado de la historia.

Reglas obligatorias:
1. texto_narrativo y resumen SIEMPRE en español. texto_narrativo de {PALABRAS_MIN_ESCENA} a
   {PALABRAS_MAX_ESCENA} palabras: escribe {LONGITUD_ESCENA}; con menos de {PALABRAS_MIN_ESCENA}
   palabras se rechaza.
2. Respeta el canon y los resúmenes previos: no contradigas nombres, rasgos, objetos, lugares ni
   relaciones ya establecidos. Usa los nombres exactos de los personajes.
3. prompt_imagen en INGLÉS, máximo {_palabras(TOKENS_MAX_PROMPT_IMAGEN)} palabras: UN sujeto
   principal haciendo la acción, la composición (por ejemplo "wide shot") y el entorno. Si el
   protagonista está en la escena, el sujeto es él. Nombra a cada personaje con su nombre
   exacto (máximo 2 personajes); un animal se nombra con su nombre, no con su especie. No
   describas rasgos ni estilo y no uses grupos ("group of friends"), salvo el grupo que pida
   la idea: si el mensaje lo indica, nómbralo en plural y sin nombres.
4. prompt_sonido en INGLÉS, máximo {PALABRAS_MAX_PROMPT_SONIDO} palabras: un ambiente y 1-2
   efectos. Sin voces ni música.
5. etiquetas_sonido: 1 a 3 valores de esta lista: {", ".join(e.value for e in EtiquetaSonido)}.
6. hechos_nuevos: hechos concretos que esta escena establece.
7. No incluyas texto fuera del JSON."""


def mensajes_plan(solicitud: StoryRequest) -> list[dict[str, str]]:
    """Mensajes para la primera etapa de la estrategia (b)."""
    regla = REGLAS_GENERO[solicitud.genero]
    return [
        {"role": "system", "content": SISTEMA_PLAN},
        {
            "role": "user",
            "content": (
                f"Idea del usuario: {solicitud.idea}\n"
                f"Género: {solicitud.genero_efectivo}\n"
                f"Indicación de género: {regla}\n"
                "Genera el plan de la historia."
            ),
        },
    ]


def _indicacion_grupos(plan: PlanHistoria) -> str:
    """13 nov: "un perro rodeado de gatos" salía con un solo gato. Si la idea pide un grupo,
    se le recuerda al LLM que lo muestre en prompt_imagen cuando esté en la escena."""
    if not plan.grupos:
        return ""
    frases = " / ".join(f'"{g.frase}"' for g in plan.grupos)
    return (
        "La idea pide un grupo: si aparece en esta escena, prompt_imagen lo dice en plural, "
        f"por ejemplo {frases}.\n"
    )


def _ficha_plan(plan: PlanHistoria) -> str:
    personajes = [
        {"id": p.id, "nombre": p.nombre, "rol": p.rol.value, "rasgos": p.rasgos_personalidad}
        for p in plan.personajes
    ]
    return json.dumps(
        {
            "titulo": plan.titulo,
            "genero": plan.genero,
            "tono": plan.tono,
            "escenario": plan.escenario.model_dump(),
            "personajes": personajes,
            "plan_escenas": [
                {"numero": e.numero, "fase": e.fase.value, "resumen": e.resumen}
                for e in plan.plan_escenas
            ],
        },
        ensure_ascii=False,
    )


def mensajes_escena(
    plan: PlanHistoria,
    numero: int,
    resumenes_previos: list[str],
    canon: list[str],
    regla_genero: str,
) -> list[dict[str, str]]:
    """Mensajes para expandir la escena ``numero`` con el canon y los resúmenes previos."""
    objetivo = plan.plan_escenas[numero - 1]
    previos = "\n".join(f"- {r}" for r in resumenes_previos) or "- (ninguna, es la primera)"
    hechos = "\n".join(f"- {h}" for h in canon) or "- (sin hechos aún)"
    return [
        {"role": "system", "content": SISTEMA_ESCENA},
        {
            "role": "user",
            "content": (
                f"Plan de la historia (JSON): {_ficha_plan(plan)}\n\n"
                f"Indicación de género: {regla_genero}\n\n"
                f"Resúmenes de las escenas ya escritas:\n{previos}\n\n"
                f"Canon vigente (no se puede contradecir):\n{hechos}\n\n"
                f"Escribe la escena {numero} (fase '{FASE_POR_NUMERO[numero].value}'). "
                f"Resumen planeado: {objetivo.resumen}\n"
                f"Personajes presentes (ids): {', '.join(objetivo.personajes_presentes)}\n"
                f"{_indicacion_grupos(plan)}"
                f"Recuerda: texto_narrativo en español, {LONGITUD_ESCENA}."
            ),
        },
    ]


# ---------------------------------------------------------------------------------------
# Ilustrador: qué se ve en la imagen de una escena (17 nov)
# ---------------------------------------------------------------------------------------
SISTEMA_PLANO_VISUAL = """Eres el director de arte de un libro ilustrado. Lees una escena ya
escrita y decides qué se ve en UNA sola ilustración. Respondes en JSON según el esquema.
Reglas:
1. principal: el id del personaje que protagoniza la imagen; debe ser uno de los presentes.
2. acompanantes: como mucho 2 figuras que se VEN junto al principal en ese momento. Cada una
   es el id de un personaje presente, o, para figuras sin nombre que el texto de la escena
   menciona, su especie o tipo en inglés, con cantidad "one", "two" o "many". No inventes
   figuras: si el texto no las nombra, no van; si el principal está solo, la lista va vacía.
3. accion: en inglés, máx. 14 palabras, lo que hace el principal en el momento más visual de
   la escena, sin nombres propios y sin repetir quién es (por ejemplo
   "looks up at the glowing rooftops").
4. lugar: en inglés, máx. 12 palabras, dónde ocurre (por ejemplo "a narrow street of an old
   city at dusk").
5. plano: "close-up" para un momento íntimo, "medium shot" para una acción, "wide shot" si
   importa el lugar o hay varias figuras."""


def mensajes_plano_visual(plan: PlanHistoria, escena: Escena) -> list[dict[str, str]]:
    """Mensajes para que el LLM describa la ilustración de ``escena`` (``PlanoVisual``)."""
    por_id = {p.id: p for p in plan.personajes}
    presentes = []
    for pid in escena.personajes_presentes:
        personaje = por_id.get(pid)
        if personaje is not None:
            tipo = personaje.descripcion_visual_fija.split(",", 1)[0]
            presentes.append(f"- {pid}: {personaje.nombre} ({tipo})")
    grupos = ""
    if plan.grupos:
        frases = " / ".join(f'"{g.frase}"' for g in plan.grupos)
        grupos = (
            f"La idea del usuario pide un grupo ({frases}): si aparece en esta escena, "
            'inclúyelo como acompañante con cantidad "many".\n'
        )
    return [
        {"role": "system", "content": SISTEMA_PLANO_VISUAL},
        {
            "role": "user",
            "content": (
                f"Escena {escena.numero}: {escena.texto_narrativo}\n\n"
                "Personajes presentes (id: nombre y tipo):\n"
                + "\n".join(presentes)
                + "\n"
                + grupos
                + "Describe la ilustración de esta escena."
            ),
        },
    ]


# ---------------------------------------------------------------------------------------
# Auditor de coherencia
# ---------------------------------------------------------------------------------------
SISTEMA_AUDITOR = """Eres un editor de continuidad. Revisas una Story Bible de 5 escenas y
devuelves en JSON (según el esquema recibido) las contradicciones que encuentres:
- nombre: un personaje cambia de nombre o se le nombra con otro.
- rasgo: cambia un rasgo físico o de personalidad sin explicación.
- hecho: una escena contradice un hecho del canon o de una escena anterior.
- escenario: cambia el lugar o la época sin justificación.
- estilo: el texto contradice el estilo visual o el tono.
- secuencia: el orden de los acontecimientos no tiene sentido.
Marca severidad "critica" solo si un lector lo notaría y rompe la historia; si no, "menor".
Indica en "escena" la escena que contiene el error (la posterior, no la que fijó el hecho).
Si no hay contradicciones, responde coherente=true y una lista vacía. No inventes problemas."""


def _bible_para_auditor(bible: StoryBible) -> str:
    datos = bible.model_dump(
        mode="json",
        exclude={
            "estilo_visual": {"negative_prompt"},
            "personajes": {"__all__": {"seed"}},
            "escenas": {"__all__": {"seed_imagen", "prompt_imagen", "prompt_sonido"}},
        },
    )
    return json.dumps(datos, ensure_ascii=False)


def mensajes_auditor(bible: StoryBible) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SISTEMA_AUDITOR},
        {"role": "user", "content": f"Story Bible a revisar (JSON):\n{_bible_para_auditor(bible)}"},
    ]


def mensajes_regenerar_escena(
    bible: StoryBible, numero: int, contradicciones: list[Contradiccion]
) -> list[dict[str, str]]:
    """Pide reescribir solo la escena ``numero`` corrigiendo las contradicciones críticas."""
    actual: Escena = bible.escena(numero)
    previos = "\n".join(f"- {r}" for r in bible.resumenes_previos(numero)) or "- (ninguna)"
    posteriores = (
        "\n".join(f"- Escena {e.numero}: {e.resumen}" for e in bible.escenas if e.numero > numero)
        or "- (ninguna)"
    )
    hechos = "\n".join(f"- {h}" for h in bible.canon_hasta(numero)) or "- (sin hechos aún)"
    problemas = "\n".join(f"- [{c.tipo}] {c.descripcion}" for c in contradicciones)
    personajes = ", ".join(f"{p.id} = {p.nombre} ({p.rol.value})" for p in bible.personajes)
    return [
        {"role": "system", "content": SISTEMA_ESCENA},
        {
            "role": "user",
            "content": (
                f"Historia: {bible.titulo} ({bible.genero}, tono {bible.tono}).\n"
                f"Personajes: {personajes}\n\n"
                f"Resúmenes previos:\n{previos}\n\n"
                f"Resúmenes posteriores (deben seguir siendo posibles):\n{posteriores}\n\n"
                f"Canon vigente:\n{hechos}\n\n"
                f"Escena {numero} actual (JSON): "
                f"{actual.model_dump_json(exclude={'seed_imagen'})}\n\n"
                f"Contradicciones detectadas por el editor:\n{problemas}\n\n"
                f"Reescribe la escena {numero} (fase '{actual.fase.value}') corrigiéndolas, con "
                f"los mismos personajes presentes: {', '.join(actual.personajes_presentes)}.\n"
                f"Recuerda: texto_narrativo en español, {LONGITUD_ESCENA}."
            ),
        },
    ]
