"""¿Los personajes del plan son los que pide la idea? (corrección del 13 nov).

Con la idea "Un grupo de amigos animales en la selva", el 4B planeó a un niño, un anciano,
un robot y un mono: el modelo de imagen dibujó fielmente al niño protagonista, y Diego vio
"un niño cuando la idea dice animales". El problema no era la imagen sino el reparto. Además,
el ejemplo de tipos del prompt ("woman, boy, old man, robot") coincidía con lo que inventó.

Aquí se revisa el reparto con reglas simples sobre la idea (en español) y el tipo de cada
personaje (la primera frase de ``descripcion_visual_fija``, en inglés):

* Si la idea habla de animales y no menciona personas, ningún personaje puede ser una
  persona ni un robot.
* Cada especie que nombra la idea ("un zorro y un búho") debe estar en algún personaje.
* 18 nov, al revés: con la regla anterior el 4B empezó a poner animales en todo ("Un niño en
  un parque infantil" salió con un zorrito y una ardilla robot; "Una chica en un edificio",
  con un zorro y una rata). Ahora cada persona que nombra la idea ("un niño", "una chica",
  "un piloto") debe estar en el reparto, y si la idea no menciona animales, ningún
  personaje puede ser uno.

El planificador usa los problemas para pedir una corrección al LLM (una vez).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final

from storybook.schemas import GrupoVisual, Personaje

# Tipos (en inglés) que no son animales.
NO_ANIMALES: Final = frozenset(
    {
        "boy", "girl", "man", "woman", "men", "women", "child", "children", "kid", "kids",
        "person", "people", "human", "teen", "teenager", "lady", "gentleman", "guy", "baby",
        "toddler", "adult", "grandmother", "grandfather", "grandma", "grandpa", "mother",
        "father", "king", "queen", "prince", "princess", "knight", "wizard", "witch", "sailor",
        "pirate", "student", "scientist", "doctor", "farmer", "cowboy", "explorer", "hunter",
        "robot", "android", "cyborg", "machine",
    }
)  # fmt: skip

# Palabras de la idea que piden personajes animales en general.
_ANIMALES_IDEA: Final = re.compile(r"\banimal(?:es|ito|itos)?\b")
# Palabras de la idea que piden (también) personas: entonces no se exige "solo animales".
_PERSONAS_IDEA: Final = re.compile(
    r"\b(?:nin[oa]s?|chic[oa]s?|hombres?|mujer(?:es)?|personas?|human[oa]s?|abuel[oa]s?|"
    r"ancian[oa]s?|jovenes|joven|universitari[oa]s?|estudiantes?|reye?s?|reinas?|"
    r"princip(?:e|es)|princesas?|piratas?|marineros?|cientific[oa]s?|familias?|padres?|"
    r"madres?|hij[oa]s?|duen[oa]s?|cazador(?:es)?|granjer[oa]s?|explorador(?:a|es)?)\b"
)

# Especie en español (regex sobre la idea sin tildes) -> nombres en inglés: singular, plural
# y otros aceptados.
_ESPECIES_ORDEN: Final[tuple[tuple[str, tuple[str, ...]], ...]] = tuple(
    (patron, tuple(ingles.split()))
    for patron, ingles in (
        (r"perr[oa]s?|perrit[oa]s?|cachorr[oa]s?", "dog dogs puppy puppies hound"),
        (r"gat[oa]s?|gatit[oa]s?", "cat cats kitten kittens"),
        (r"zorr[oa]s?|zorrit[oa]s?", "fox foxes"),
        (r"conej[oa]s?|conejit[oa]s?", "rabbit rabbits bunny bunnies hare"),
        (r"os[oa]s?|osit[oa]s?", "bear bears cub"),
        (r"lob[oa]s?", "wolf wolves"),
        (r"jaguar(?:es)?", "jaguar jaguars"),
        (r"tigre(?:s)?", "tiger tigers"),
        (r"leon(?:es)?|leonas?", "lion lions lioness"),
        (r"monos?|monit[oa]s?", "monkey monkeys ape chimpanzee"),
        (r"tucan(?:es)?", "toucan toucans"),
        (r"lor[oa]s?|guacamayas?|papagayos?", "parrot parrots macaw"),
        (r"tortugas?", "turtle turtles tortoise"),
        (r"elefantes?", "elephant elephants"),
        (r"buhos?|lechuzas?", "owl owls"),
        (r"pajar[oa]s?|pajarit[oa]s?|aves?", "bird birds"),
        (r"pez|peces|pececit[oa]s?", "fish fish"),
        (r"raton(?:es)?|ratoncit[oa]s?", "mouse mice"),
        (r"ranas?|sapos?", "frog frogs toad"),
        (r"dragon(?:es)?", "dragon dragons"),
        (r"caball[oa]s?|ponis?", "horse horses pony"),
        (r"ardillas?", "squirrel squirrels"),
        (r"serpientes?|culebras?", "snake snakes serpent"),
        (r"delfin(?:es)?", "dolphin dolphins"),
        (r"ballenas?", "whale whales"),
        (r"pinguinos?", "penguin penguins"),
        (r"jirafas?", "giraffe giraffes"),
        (r"cocodrilos?|caiman(?:es)?", "crocodile crocodiles alligator caiman"),
        (r"mariposas?", "butterfly butterflies"),
        (r"abejas?", "bee bees"),
        (r"erizos?", "hedgehog hedgehogs"),
        (r"mapaches?", "raccoon raccoons"),
        (r"capibaras?|chiguiros?", "capybara capybaras"),
        (r"colibries?|colibri", "hummingbird hummingbirds"),
        (r"aguilas?", "eagle eagles"),
        (r"condor(?:es)?", "condor condors"),
        (r"venados?|ciervos?", "deer deer fawn"),
        (r"unicornios?", "unicorn unicorns"),
        (r"pulpos?", "octopus octopuses"),
    )
)
ESPECIES: Final[tuple[tuple[str, frozenset[str]], ...]] = tuple(
    (patron, frozenset(nombres)) for patron, nombres in _ESPECIES_ORDEN
)
# Persona en español (regex sobre la idea sin tildes) -> tipos en inglés aceptados (una
# palabra o dos, como "old man"). 18 nov.
_PERSONAS_ORDEN: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (r"nin[oa]s?|nen[ea]s?|chiquill[oa]s?|pequen[oa]s?",
     ("boy", "girl", "child", "kid", "children", "kids", "toddler")),
    (r"chicas?|muchachas?|jovencitas?",
     ("girl", "young woman", "teenage girl", "teen", "woman", "teenager")),
    (r"chicos?|muchachos?|jovencitos?",
     ("boy", "young man", "teenage boy", "teen", "man", "teenager")),
    (r"jovenes|joven", ("young man", "young woman", "teen", "teenager", "boy", "girl")),
    (r"bebes?", ("baby", "toddler", "infant")),
    (r"hombres?|senor(?:es)?", ("man", "men", "gentleman")),
    (r"mujer(?:es)?|senoras?|damas?", ("woman", "women", "lady")),
    (r"ancian[oa]s?|viejit[oa]s?",
     ("old man", "old woman", "elderly man", "elderly woman", "grandfather", "grandmother")),
    (r"abuel[oa]s?", ("grandfather", "grandmother", "old man", "old woman", "grandpa", "grandma")),
    (r"pilotos?", ("pilot",)),
    (r"astronautas?", ("astronaut",)),
    (r"detectives?", ("detective",)),
    (r"cientific[oa]s?", ("scientist",)),
    (r"doctor(?:a|es)?|medic[oa]s?", ("doctor",)),
    (r"enfermer[oa]s?", ("nurse",)),
    (r"policias?", ("police officer", "policeman", "policewoman", "officer")),
    (r"bomber[oa]s?", ("firefighter", "fireman")),
    (r"maestr[oa]s?|profesor(?:a|es)?", ("teacher", "professor")),
    (r"estudiantes?|alumn[oa]s?", ("student",)),
    (r"princesas?", ("princess",)),
    (r"princip(?:e|es)", ("prince",)),
    (r"reye?s?", ("king",)),
    (r"reinas?", ("queen",)),
    (r"caballeros?", ("knight",)),
    (r"piratas?", ("pirate",)),
    (r"brujas?|bruj[oa]s?", ("witch", "wizard", "sorcerer", "sorceress")),
    (r"mag[oa]s?|hechicer[oa]s?", ("wizard", "witch", "sorcerer", "sorceress", "mage", "magician")),
    (r"marineros?", ("sailor",)),
    (r"granjer[oa]s?|campesin[oa]s?", ("farmer", "peasant")),
    (r"cazador(?:a|es)?", ("hunter",)),
    (r"explorador(?:a|es)?", ("explorer",)),
    (r"vaquer[oa]s?", ("cowboy", "cowgirl")),
    (r"soldados?", ("soldier",)),
    (r"robots?", ("robot", "android")),
)  # fmt: skip

# Animales reales (en inglés) que no están en ESPECIES: para saber si un personaje es un
# animal que la idea no pidió. Los fantásticos (dragón, unicornio) no cuentan.
_ANIMALES_EXTRA: Final = frozenset(
    {
        "rat", "hamster", "goat", "sheep", "lamb", "cow", "bull", "ox", "pig", "duck",
        "chicken", "hen", "rooster", "lizard", "bat", "spider", "ant", "crow", "raven", "seal",
        "otter", "beaver", "badger", "koala", "panda", "kangaroo", "zebra", "buffalo", "rhino",
        "hippo", "camel", "llama", "alpaca", "sloth", "bison", "moose", "shark", "crab",
        "snail", "beetle", "ladybug", "dinosaur", "cub", "kitten", "puppy", "pup", "ferret",
        "mole", "weasel", "skunk", "possum", "opossum", "porcupine", "armadillo", "lemur",
        "gorilla", "orangutan", "chimpanzee", "panther", "leopard", "cheetah", "lynx", "hyena",
        "coyote", "jackal", "squid", "jellyfish", "starfish", "flamingo", "pelican", "swan",
        "goose", "pigeon", "sparrow", "robin", "hawk", "falcon", "vulture", "stork", "heron",
        "gecko", "iguana", "chameleon", "tortoise", "toad", "salamander", "fawn",
    }
)  # fmt: skip
_FANTASTICOS: Final = frozenset({"dragon", "dragons", "unicorn", "unicorns"})

# Palabras que, junto a un plural, piden un grupo ("rodeado de gatos", "una manada de lobos").
_CANTIDAD_EXACTA: Final = re.compile(r"\b(?:dos|tres|cuatro|cinco|par)\s+(?:de\s+)?$")


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()


def tipo(personaje: Personaje) -> str:
    """'boy age 10, curly hair' -> 'boy'; 'young jaguar age 4' -> 'young jaguar'."""
    primera = personaje.descripcion_visual_fija.split(",", 1)[0].strip()
    primera = re.sub(r"^(?:a|an|the)\s+", "", primera, flags=re.IGNORECASE)
    return re.split(r"\s+age\b", primera, maxsplit=1)[0].strip().lower()


def _palabras(texto: str) -> set[str]:
    return set(re.findall(r"[a-z]+", texto.lower()))


def es_persona_o_maquina(personaje: Personaje) -> bool:
    return bool(_palabras(tipo(personaje)) & NO_ANIMALES)


def _en_la_idea(idea: str, palabra: str) -> str:
    """'nino' -> 'niño' tal como la escribió el usuario (si se puede ubicar)."""
    normalizada = _normalizar(idea)
    inicio = normalizada.find(palabra)
    if inicio < 0 or len(normalizada) != len(idea):
        return palabra
    return idea[inicio : inicio + len(palabra)].lower()


def personas_pedidas(idea: str) -> list[tuple[str, tuple[str, ...]]]:
    """Personas que nombra la idea: (palabra en español, tipos en inglés aceptados)."""
    texto = _normalizar(idea)
    pedidas = []
    for patron, ingles in _PERSONAS_ORDEN:
        coincidencia = re.search(rf"\b(?:{patron})\b", texto)
        if coincidencia and all(ingles != otra for _, otra in pedidas):
            pedidas.append((coincidencia.group(0), ingles))
    return pedidas


def _es_tipo(personaje: Personaje, aceptados: Sequence[str]) -> bool:
    """El tipo del personaje ('young woman', 'little girl') es uno de los aceptados."""
    texto = f" {' '.join(re.findall(r'[a-z]+', tipo(personaje)))} "
    return any(f" {a} " in texto for a in aceptados)


def es_animal(personaje: Personaje) -> bool:
    """Animal real según el tipo ('young fox', 'old rat'); personas y robots no lo son."""
    palabras = _palabras(tipo(personaje))
    if palabras & NO_ANIMALES:
        return False
    animales = _ANIMALES_EXTRA.union(*(nombres for _, nombres in ESPECIES)) - _FANTASTICOS
    return bool(palabras & animales)


def menciona_animales(idea: str) -> bool:
    return bool(_ANIMALES_IDEA.search(_normalizar(idea))) or bool(especies_pedidas(idea))


def especies_pedidas(idea: str) -> list[tuple[str, frozenset[str]]]:
    """Especies que nombra la idea: (palabra en español, nombres en inglés aceptados)."""
    texto = _normalizar(idea)
    pedidas = []
    for patron, ingles in ESPECIES:
        coincidencia = re.search(rf"\b(?:{patron})\b", texto)
        if coincidencia and all(ingles != otra for _, otra in pedidas):
            pedidas.append((coincidencia.group(0), ingles))
    return pedidas


def solo_animales(idea: str) -> bool:
    """La idea pide animales y no menciona personas."""
    texto = _normalizar(idea)
    pide_animales = bool(_ANIMALES_IDEA.search(texto)) or bool(especies_pedidas(idea))
    return pide_animales and not _PERSONAS_IDEA.search(texto)


def problemas_reparto(idea: str, personajes: Sequence[Personaje]) -> list[str]:
    """Diferencias entre la idea y el reparto, como frases para devolverle al LLM."""
    problemas: list[str] = []
    if solo_animales(idea):
        intrusos = [p for p in personajes if es_persona_o_maquina(p)]
        if intrusos:
            lista = ", ".join(f"'{p.nombre}' es '{tipo(p)}'" for p in intrusos)
            problemas.append(
                f"La idea pide personajes animales y no menciona personas, pero {lista}. "
                "Esos personajes deben ser animales."
            )
    elif not menciona_animales(idea):
        animales = [p for p in personajes if es_animal(p)]
        if animales:
            lista = ", ".join(f"'{p.nombre}' es '{tipo(p)}'" for p in animales)
            problemas.append(
                f"La idea no menciona animales, pero {lista}. Esos personajes deben ser "
                "personas (o lo que la idea nombra)."
            )
    for palabra, aceptados in personas_pedidas(idea):
        if not any(_es_tipo(p, aceptados) for p in personajes):
            palabra = _en_la_idea(idea, palabra)
            problemas.append(
                f"La idea nombra '{palabra}', pero ningún personaje lo es. El protagonista debe "
                f"ser '{aceptados[0]}' (el tipo en inglés al inicio del descriptor)."
            )
    descriptores = [_palabras(p.descripcion_visual_fija) for p in personajes]
    for palabra, ingles in especies_pedidas(idea):
        if not any(d & ingles for d in descriptores):
            ejemplo = sorted(ingles)[0]
            problemas.append(
                f"La idea nombra '{palabra}', pero ningún personaje lo es. Uno de los personajes "
                f"(el protagonista, si la idea gira en torno a él) debe ser '{ejemplo}'."
            )
    return problemas


def singular_ingles(palabra: str) -> str:
    """'cats' -> 'cat', 'foxes' -> 'fox', 'wolves' -> 'wolf', 'butterflies' -> 'butterfly'."""
    irregulares = {
        "wolves": "wolf", "mice": "mouse", "geese": "goose", "children": "child",
        "people": "person", "men": "man", "women": "woman",
    }  # fmt: skip
    if palabra in irregulares:
        return irregulares[palabra]
    if palabra.endswith("ies") and len(palabra) > 4:
        return palabra[:-3] + "y"
    if palabra.endswith(("ches", "shes", "xes", "sses")):
        return palabra[:-2]
    if palabra.endswith("s") and not palabra.endswith(("ss", "us", "is")):
        return palabra[:-1]
    return palabra


def mencionado(figura: str, texto_es: str, texto_en: str) -> bool:
    """¿La escena nombra esta figura sin nombre ("cat", "many children", "book")?

    18 nov: el ilustrador puso "many cats" en la historia del dragón porque su ejemplo decía
    "cat". Se busca el sustantivo en el prompt_imagen (inglés) y, para especies y personas,
    sus nombres en español en el texto de la escena.
    """
    palabras = re.findall(r"[a-z]+", figura.lower())
    if not palabras:
        return False
    nucleo = singular_ingles(palabras[-1])
    en = {singular_ingles(w) for w in re.findall(r"[a-z]+", texto_en.lower())}
    if nucleo in en:
        return True
    es = _normalizar(texto_es)
    for patron, nombres in _ESPECIES_ORDEN:
        if (nucleo in nombres or palabras[-1] in nombres) and re.search(rf"\b(?:{patron})\b", es):
            return True
    for patron, tipos in _PERSONAS_ORDEN:
        nucleos = {t.split()[-1] for t in tipos}
        if {nucleo, palabras[-1]} & nucleos and re.search(rf"\b(?:{patron})\b", es):
            return True
    return False


def mensaje_correccion(problemas: Sequence[str]) -> str:
    lista = "\n".join(f"- {p}" for p in problemas)
    return (
        "El reparto no coincide con la idea del usuario:\n"
        f"{lista}\n"
        "Corrige SOLO esos personajes: en descripcion_visual_fija, el tipo en inglés es la "
        "persona o la especie que pide la idea (por ejemplo 'girl age 12' o 'young jaguar age "
        "4'); dales nombres que encajen y ajusta los "
        "ids en plan_escenas si cambian. Mantén lo demás: titulo, tono, resúmenes y "
        "canon_inicial en español. Devuelve el plan completo."
    )


def grupos_pedidos(idea: str) -> list[GrupoVisual]:
    """Grupos que pide la idea, para que se vean en las ilustraciones.

    "Un perro rodeado de gatos" -> "surrounded by many cats" en las escenas con un gato;
    "Un grupo de amigos animales" -> "with a group of animal friends" en las escenas con dos o
    más personajes. Un número exacto ("dos zorros") no es un grupo: el LLM los nombra uno a uno.
    """
    texto = _normalizar(idea)
    rodeado = "rodead" in texto
    grupos: list[GrupoVisual] = []
    for patron, nombres in _ESPECIES_ORDEN:
        for coincidencia in re.finditer(rf"\b(?:{patron})\b", texto):
            palabra = coincidencia.group(0)
            if not palabra.endswith("s") or _CANTIDAD_EXACTA.search(texto[: coincidencia.start()]):
                continue
            singular, plural = nombres[0], nombres[1]
            frase = f"surrounded by many {plural}" if rodeado else f"with several {plural}"
            grupos.append(GrupoVisual(frase=frase, especie=singular, plural=plural))
            break
    if not grupos and re.search(r"\banimal(?:es|itos)\b", texto):
        amigos = re.search(r"\bamig[oa]s\b", texto)
        frase = "with a group of animal friends" if amigos else "with a group of animals"
        grupos.append(GrupoVisual(frase=frase))
    return grupos[:3]
