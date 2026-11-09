"""Plantillas de prompts para el LLM. Los límites numéricos vienen de ``schemas`` para que
prompt y validación nunca se desincronicen."""

from __future__ import annotations

from storybook.schemas import (
    MAX_PERSONAJES,
    MIN_ESCENAS_PROTAGONISTA,
    PALABRAS_MAX_ESCENA,
    PALABRAS_MAX_PROMPT_SONIDO,
    PALABRAS_MIN_ESCENA,
    TOKENS_MAX_DESCRIPTOR,
    TOKENS_MAX_ESTILO,
    TOKENS_MAX_PROMPT_IMAGEN,
    EtiquetaSonido,
    Genero,
    StoryRequest,
)

# Margen para las comas: el esquema limita tokens (palabras + signos), el prompt habla de palabras.
_FACTOR_PALABRAS = 0.75


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
2. texto_narrativo en español, de {PALABRAS_MIN_ESCENA} a {PALABRAS_MAX_ESCENA} palabras por escena.
3. Entre 1 y {MAX_PERSONAJES} personajes; exactamente uno con rol "protagonista", presente en la
   escena 1 y en al menos {MIN_ESCENAS_PROTAGONISTA} escenas. Usa siempre el mismo nombre.
4. Los campos para el ilustrador y el sonidista van en INGLÉS, como frases breves separadas por
   comas (cada coma también consume espacio del modelo de imagen):
   - estilo_visual (tecnica + paleta + iluminacion): máximo {_palabras(TOKENS_MAX_ESTILO)} palabras
     en total.
   - descripcion_visual_fija: máximo {_palabras(TOKENS_MAX_DESCRIPTOR)} palabras: edad, complexión,
     cabello, ropa y un rasgo distintivo. No describas el estado de ánimo.
   - prompt_imagen: máximo {_palabras(TOKENS_MAX_PROMPT_IMAGEN)} palabras, SOLO acción, composición
     y entorno. No repitas la descripción del personaje ni el estilo: se añaden automáticamente.
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


def mensaje_reparacion(errores: list[str]) -> dict[str, str]:
    """Mensaje que devuelve al modelo los errores de validación para que corrija."""
    lista = "\n".join(f"- {e}" for e in errores[:12])
    return {
        "role": "user",
        "content": (
            "El JSON anterior no pasó la validación. Corrige SOLO estos problemas y devuelve "
            f"la Story Bible completa:\n{lista}"
        ),
    }
