"""Síntesis procedural de ambientes (fallback C): numpy + scipy, sin modelos ni licencias.

Cada ``EtiquetaSonido`` del esquema tiene una receta. Así el fallback de sonido siempre
encuentra algo pertinente aunque no haya GPU, modelos ni biblioteca: la historia nunca se
queda sin ambiente. Las recetas son aproximaciones explicables (ruido filtrado, osciladores,
envolventes y eventos de Poisson), no grabaciones; su objetivo es que el ambiente se
distinga de la voz y acompañe la escena.

Todas las recetas son deterministas con la ``seed`` (``numpy.random.default_rng``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Final

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

from storybook.schemas import EtiquetaSonido

FRECUENCIA: Final = 44_100
PICO_SALIDA: Final = 0.7  # -3 dBFS: deja margen al mezclador
FUNDIDO_S: Final = 0.3
GANANCIAS_CAPAS: Final = (1.0, 0.5, 0.35)  # la primera etiqueta manda

Receta = Callable[[np.random.Generator, int, int], np.ndarray]


# ---------------------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------------------
def _t(n: int, sr: int) -> np.ndarray:
    return np.arange(n) / sr


def _filtrar(x: np.ndarray, sr: int, tipo: str, corte: float | tuple[float, float]) -> np.ndarray:
    sos = butter(4, corte, btype=tipo, fs=sr, output="sos")
    return sosfilt(sos, x)


def _ruido(rng: np.random.Generator, n: int) -> np.ndarray:
    return rng.standard_normal(n)


def _normalizar(x: np.ndarray) -> np.ndarray:
    pico = float(np.max(np.abs(x))) if x.size else 0.0
    return x / pico if pico > 0 else x


def _modulacion_lenta(rng: np.random.Generator, n: int, sr: int, hz: float) -> np.ndarray:
    """Envolvente aleatoria suave entre ~0,2 y 1 (ruido filtrado a ``hz``)."""
    env = _filtrar(_ruido(rng, n), sr, "lowpass", hz)
    env = _normalizar(env)
    return 0.6 + 0.4 * env


def _eventos(
    rng: np.random.Generator,
    n: int,
    sr: int,
    por_segundo: float,
    evento: Callable[[np.random.Generator], np.ndarray],
) -> np.ndarray:
    """Suma eventos cortos en instantes de Poisson."""
    salida = np.zeros(n)
    cantidad = rng.poisson(por_segundo * n / sr)
    for inicio in rng.integers(0, max(n - 1, 1), size=cantidad):
        e = evento(rng)
        fin = min(n, inicio + e.size)
        salida[inicio:fin] += e[: fin - inicio]
    return salida


def _colocar(n: int, evento: np.ndarray, inicio: int) -> np.ndarray:
    """Señal de longitud ``n`` con ``evento`` a partir de la muestra ``inicio``."""
    salida = np.zeros(n)
    if 0 <= inicio < n:
        fin = min(n, inicio + evento.size)
        salida[inicio:fin] = evento[: fin - inicio]
    return salida


def _periodico(
    n: int, sr: int, periodo_s: float, evento: np.ndarray, desfase_s: float = 0.0
) -> np.ndarray:
    salida = np.zeros(n)
    paso = int(periodo_s * sr)
    for inicio in range(int(desfase_s * sr), n, max(paso, 1)):
        fin = min(n, inicio + evento.size)
        salida[inicio:fin] += evento[: fin - inicio]
    return salida


def _decaimiento(sr: int, duracion_s: float, tau_s: float) -> np.ndarray:
    return np.exp(-_t(int(duracion_s * sr), sr) / tau_s)


def _tono(sr: int, frecuencia: float, duracion_s: float, tau_s: float) -> np.ndarray:
    t = _t(int(duracion_s * sr), sr)
    return np.sin(2 * np.pi * frecuencia * t) * np.exp(-t / tau_s)


def _reverberar(x: np.ndarray, sr: int, cola_s: float, rng: np.random.Generator) -> np.ndarray:
    ir = _ruido(rng, int(cola_s * sr)) * _decaimiento(sr, cola_s, cola_s / 4)
    ir[0] = 1.0
    return fftconvolve(x, ir * 0.3)[: x.size]


# ---------------------------------------------------------------------------------------
# Recetas (una por etiqueta del esquema)
# ---------------------------------------------------------------------------------------
def viento(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    grave = _filtrar(_ruido(rng, n), sr, "bandpass", (150, 700)) * _modulacion_lenta(
        rng, n, sr, 0.3
    )
    silbido = _filtrar(_ruido(rng, n), sr, "bandpass", (600, 1400)) * _modulacion_lenta(
        rng, n, sr, 0.15
    )
    return grave + 0.4 * silbido


def lluvia(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    fondo = _filtrar(_ruido(rng, n), sr, "highpass", 1500) * 0.5

    def gota(r: np.random.Generator) -> np.ndarray:
        return _ruido(r, int(0.004 * sr)) * _decaimiento(sr, 0.004, 0.001) * r.uniform(0.2, 1)

    gotas = _filtrar(_eventos(rng, n, sr, 120, gota), sr, "bandpass", (2000, 9000))
    return fondo + gotas


def trueno(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    retumbo = _filtrar(_ruido(rng, n), sr, "lowpass", 150) * 0.25

    def descarga(r: np.random.Generator) -> np.ndarray:
        t = _t(int(3.0 * sr), sr)
        envolvente = (1 - np.exp(-t / 0.05)) * np.exp(-t / 0.8)
        return _filtrar(_ruido(r, t.size), sr, "lowpass", 300) * envolvente * 4

    # Una descarga segura al principio y otras al azar.
    return (
        retumbo + _colocar(n, descarga(rng), int(0.5 * sr)) + _eventos(rng, n, sr, 0.15, descarga)
    )


def fuego(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    rugido = _filtrar(_ruido(rng, n), sr, "lowpass", 500) * _modulacion_lenta(rng, n, sr, 2)

    def chasquido(r: np.random.Generator) -> np.ndarray:
        return _ruido(r, int(0.003 * sr)) * _decaimiento(sr, 0.003, 0.0008) * r.uniform(0.5, 3)

    chasquidos = _filtrar(_eventos(rng, n, sr, 8, chasquido), sr, "highpass", 1500)
    # Los chasquidos son muy cortos: se equilibran por energía para que el rugido se oiga.
    return _normalizar(rugido) + 0.25 * _normalizar(chasquidos)


def arroyo(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    burbujeo = 0.4 + 0.6 * np.abs(_normalizar(_filtrar(_ruido(rng, n), sr, "lowpass", 8)))
    return _filtrar(_ruido(rng, n), sr, "bandpass", (400, 3000)) * burbujeo


def olas(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    periodo = rng.uniform(6, 8)
    oleaje = (0.5 * (1 - np.cos(2 * np.pi * _t(n, sr) / periodo))) ** 2
    cuerpo = _filtrar(_ruido(rng, n), sr, "lowpass", 1200) * (0.15 + oleaje)
    espuma = _filtrar(_ruido(rng, n), sr, "highpass", 3000) * oleaje**2 * 0.3
    return cuerpo + espuma


def pajaros(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    def trino(r: np.random.Generator) -> np.ndarray:
        dur = r.uniform(0.08, 0.2)
        t = _t(int(dur * sr), sr)
        f0, f1 = r.uniform(2500, 4500), r.uniform(3000, 5500)
        fase = 2 * np.pi * (f0 * t + (f1 - f0) * t**2 / (2 * dur))
        fase += 3 * np.sin(2 * np.pi * 40 * t)  # vibrato
        silaba = np.sin(fase) * np.sin(np.pi * t / dur) ** 2
        repeticiones = int(r.integers(1, 4))
        hueco = np.zeros(int(0.06 * sr))
        return np.concatenate([np.concatenate([silaba, hueco])] * repeticiones) * r.uniform(0.3, 1)

    return _eventos(rng, n, sr, 1.5, trino)


def bosque(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    return 0.35 * _normalizar(viento(rng, n, sr)) + _normalizar(pajaros(rng, n, sr))


def insectos_nocturnos(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    t = _t(n, sr)
    portadora = np.sin(2 * np.pi * 4500 * t)
    pulsos = (np.sin(2 * np.pi * 30 * t) > 0).astype(float)
    grupos = (np.sin(2 * np.pi * 1.6 * t) > 0.2).astype(float)
    envolvente = _filtrar(pulsos * grupos, sr, "lowpass", 200)
    fondo = _filtrar(_ruido(rng, n), sr, "bandpass", (3000, 7000)) * 0.05
    return portadora * envolvente + fondo


def pasos(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    def paso(r: np.random.Generator) -> np.ndarray:
        golpe = _filtrar(_ruido(r, int(0.08 * sr)), sr, "lowpass", 400)
        roce = _filtrar(_ruido(r, int(0.08 * sr)), sr, "highpass", 2000) * 0.2
        return (golpe + roce) * _decaimiento(sr, 0.08, 0.02) * r.uniform(0.7, 1)

    salida = np.zeros(n)
    instante = rng.uniform(0, 0.3)
    while instante * sr < n:
        e = paso(rng)
        i = int(instante * sr)
        fin = min(n, i + e.size)
        salida[i:fin] += e[: fin - i]
        instante += rng.uniform(0.5, 0.6)
    return salida


def latidos(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    lub = _tono(sr, 50, 0.25, 0.06) + 0.5 * _tono(sr, 80, 0.25, 0.04)
    dub = 0.6 * (_tono(sr, 60, 0.2, 0.05) + 0.5 * _tono(sr, 95, 0.2, 0.03))
    latido = _colocar(int(0.6 * sr), lub, 0) + _colocar(int(0.6 * sr), dub, int(0.28 * sr))
    return _periodico(n, sr, 60 / rng.uniform(62, 72), latido)


def puerta_que_cruje(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    def crujido(r: np.random.Generator) -> np.ndarray:
        dur = r.uniform(1.2, 2.0)
        t = _t(int(dur * sr), sr)
        frecuencia = 110 + 120 * t / dur + 15 * _filtrar(_ruido(r, t.size), sr, "lowpass", 20)
        diente = 2 * ((np.cumsum(frecuencia) / sr) % 1) - 1
        envolvente = np.sin(np.pi * t / dur) ** 0.5
        return _filtrar(diente * envolvente, sr, "bandpass", (300, 2500))

    return _colocar(n, crujido(rng), int(0.3 * sr)) + _eventos(rng, n, sr, 0.15, crujido)


def multitud(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    salida = np.zeros(n)
    for _ in range(8):
        centro = rng.uniform(400, 2500)
        voz = _filtrar(_ruido(rng, n), sr, "bandpass", (centro * 0.7, centro * 1.3))
        silabas = np.clip(_normalizar(_filtrar(_ruido(rng, n), sr, "lowpass", 5)), 0, None)
        salida += voz * silabas
    return _filtrar(salida, sr, "lowpass", 3500)


def ciudad(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    trafico = _filtrar(_ruido(rng, n), sr, "lowpass", 200) * _modulacion_lenta(rng, n, sr, 0.2)
    murmullo = _filtrar(_ruido(rng, n), sr, "bandpass", (300, 2000)) * 0.15

    def bocina(r: np.random.Generator) -> np.ndarray:
        t = _t(int(0.4 * sr), sr)
        tono = np.sign(np.sin(2 * np.pi * 400 * t)) + np.sign(np.sin(2 * np.pi * 500 * t))
        return _filtrar(tono, sr, "lowpass", 2000) * 0.15 * r.uniform(0.5, 1)

    return trafico + murmullo + _eventos(rng, n, sr, 0.1, bocina)


def maquinaria(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    t = _t(n, sr)
    zumbido = sum(np.sin(2 * np.pi * 55 * k * t) / k for k in range(1, 7))
    golpe = sum(_tono(sr, f, 0.3, 0.06) for f in (800, 1240, 1900)) / 3
    return 0.6 * zumbido + _periodico(n, sr, rng.uniform(0.7, 0.9), golpe)


def zumbido_nave(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    t = _t(n, sr)
    tonos = np.sin(2 * np.pi * 40 * t) + 0.6 * np.sin(2 * np.pi * 80.5 * t)
    tonos += 0.4 * np.sin(2 * np.pi * 120.3 * t)
    aire = _filtrar(_ruido(rng, n), sr, "lowpass", 300) * 0.3
    return (tonos + aire) * _modulacion_lenta(rng, n, sr, 0.1)


def dron_oscuro(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    t = _t(n, sr)
    tonos = sum(np.sin(2 * np.pi * f * t) for f in (55.0, 55.7, 82.4, 110.3))
    sombra = _filtrar(_ruido(rng, n), sr, "lowpass", 200) * 0.5
    oleaje = 0.6 + 0.4 * np.sin(2 * np.pi * t / rng.uniform(6, 10))
    return (tonos + sombra) * oleaje


def brillo_magico(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    notas = (1046.5, 1174.7, 1318.5, 1568.0, 1760.0, 2093.0)

    def destello(r: np.random.Generator) -> np.ndarray:
        f = float(r.choice(notas))
        return (_tono(sr, f, 1.5, 0.4) + 0.3 * _tono(sr, 2 * f, 1.5, 0.25)) * r.uniform(0.3, 1)

    t = _t(n, sr)
    colchon = (np.sin(2 * np.pi * 523.25 * t) + np.sin(2 * np.pi * 784.0 * t)) * 0.08
    return _eventos(rng, n, sr, 4, destello) + colchon


def campanas(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    fundamental = rng.uniform(380, 480)
    parciales = ((0.56, 3.0), (0.92, 2.5), (1.19, 2.0), (1.71, 1.5), (2.0, 1.2), (2.74, 1.0))
    golpe = sum(
        _tono(sr, fundamental * relacion, 4.0, tau) / (i + 1)
        for i, (relacion, tau) in enumerate(parciales)
    )
    return _periodico(n, sr, rng.uniform(2.2, 3.0), golpe, desfase_s=0.2)


def goteo_cueva(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    def gota(r: np.random.Generator) -> np.ndarray:
        dur = 0.04
        t = _t(int(dur * sr), sr)
        f = r.uniform(900, 1800) * (1 + 0.6 * t / dur)
        return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / 0.01)

    gotas = _eventos(rng, n, sr, 1.2, gota)
    sala = _filtrar(_ruido(rng, n), sr, "lowpass", 120) * 0.08
    return _reverberar(gotas, sr, 1.2, rng) + sala


def reloj(rng: np.random.Generator, n: int, sr: int) -> np.ndarray:
    def golpe(frecuencia: float) -> np.ndarray:
        clic = _filtrar(_ruido(rng, int(0.003 * sr)), sr, "highpass", 3000)
        return _colocar(int(0.025 * sr), _tono(sr, frecuencia, 0.025, 0.005), 0) + _colocar(
            int(0.025 * sr), clic, 0
        )

    tic_tac = _colocar(sr, golpe(2000), 0) + _colocar(sr, golpe(1600), sr // 2)
    return _periodico(n, sr, 1.0, tic_tac)


RECETAS: Final[dict[EtiquetaSonido, Receta]] = {
    EtiquetaSonido.WIND: viento,
    EtiquetaSonido.RAIN: lluvia,
    EtiquetaSonido.THUNDER: trueno,
    EtiquetaSonido.FIRE: fuego,
    EtiquetaSonido.WATER_STREAM: arroyo,
    EtiquetaSonido.OCEAN_WAVES: olas,
    EtiquetaSonido.FOREST: bosque,
    EtiquetaSonido.BIRDS: pajaros,
    EtiquetaSonido.NIGHT_INSECTS: insectos_nocturnos,
    EtiquetaSonido.FOOTSTEPS: pasos,
    EtiquetaSonido.HEARTBEAT: latidos,
    EtiquetaSonido.DOOR_CREAK: puerta_que_cruje,
    EtiquetaSonido.CROWD: multitud,
    EtiquetaSonido.CITY: ciudad,
    EtiquetaSonido.MACHINERY: maquinaria,
    EtiquetaSonido.SPACESHIP_HUM: zumbido_nave,
    EtiquetaSonido.DARK_DRONE: dron_oscuro,
    EtiquetaSonido.MAGIC_SHIMMER: brillo_magico,
    EtiquetaSonido.BELLS: campanas,
    EtiquetaSonido.CAVE_DRIPS: goteo_cueva,
    EtiquetaSonido.CLOCK_TICKING: reloj,
}


# ---------------------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------------------
def sintetizar(
    etiquetas: Sequence[str | EtiquetaSonido],
    duracion_s: float,
    frecuencia: int = FRECUENCIA,
    seed: int = 0,
) -> np.ndarray:
    """Ambiente mono float32 de ``duracion_s`` con las recetas de ``etiquetas`` (máx. 3).

    La primera etiqueta es la capa principal; las demás se suman más bajas. Pico a
    ``PICO_SALIDA`` y fundidos cortos de entrada y salida (el mezclador hace el loop).
    """
    if duracion_s <= 0:
        raise ValueError("duracion_s debe ser positiva")
    elegidas = [EtiquetaSonido(e) for e in etiquetas][: len(GANANCIAS_CAPAS)] or [
        EtiquetaSonido.WIND
    ]
    n = round(duracion_s * frecuencia)
    rng = np.random.default_rng(seed)
    mezcla = np.zeros(n)
    for ganancia, etiqueta in zip(GANANCIAS_CAPAS, elegidas, strict=False):
        capa = np.nan_to_num(RECETAS[etiqueta](rng, n, frecuencia)[:n])
        mezcla[: capa.size] += ganancia * _normalizar(capa)
    mezcla = _normalizar(mezcla) * PICO_SALIDA
    fundido = min(int(FUNDIDO_S * frecuencia), n // 2)
    if fundido:
        rampa = np.linspace(0.0, 1.0, fundido)
        mezcla[:fundido] *= rampa
        mezcla[-fundido:] *= rampa[::-1]
    return mezcla.astype(np.float32)
