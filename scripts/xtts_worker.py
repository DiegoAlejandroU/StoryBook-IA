"""Proceso de voz XTTS-v2 (perfil Avanzada, 18 nov). Corre en ``.venv-xtts``, no en la app.

XTTS-v2 (coqui-tts) necesita ``torchaudio``, que no existe para la versión de torch de la
app (2.15); por eso vive en un entorno aparte con torch 2.11 y la app le habla por
stdin/stdout, una línea JSON por pedido:

    {"cmd": "narrar", "texto": "...", "salida": "C:/.../voice_1.wav",
     "speaker": "Ana Florence", "idioma": "es"}
    -> {"ok": true, "segundos": 9.8, "duracion_s": 41.2, "sample_rate": 24000, "gpu": true}
    {"cmd": "salir"}

El modelo se carga una vez en la RAM y pasa a la GPU solo mientras narra (la GPU de 4 GB la
comparten FLUX, Stable Audio y el LLM). Si la GPU no alcanza, esa escena se narra en CPU.

Licencia del modelo: Coqui Public Model License (uso no comercial), aceptada por Diego el
18 nov. Pesos del repositorio oficial ``coqui/XTTS-v2`` (descargados por
``download_models.py``); este proceso no usa Internet.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

MAX_CARACTERES = 220  # XTTS corta en ~239 caracteres en español; se deja margen
PAUSA_S = 0.18  # silencio entre fragmentos


def fragmentos(texto: str, maximo: int = MAX_CARACTERES) -> list[str]:
    """Oraciones agrupadas en trozos de hasta ``maximo`` caracteres (sin cortar palabras)."""
    oraciones = [o.strip() for o in re.split(r"(?<=[.!?…;:])\s+", texto.strip()) if o.strip()]
    trozos: list[str] = []
    actual = ""
    for oracion in oraciones:
        while len(oracion) > maximo:  # oración muy larga: se parte por comas o espacios
            corte = oracion.rfind(",", 0, maximo)
            corte = corte if corte > maximo // 2 else oracion.rfind(" ", 0, maximo)
            corte = corte if corte > 0 else maximo
            if actual:
                trozos.append(actual)
                actual = ""
            trozos.append(oracion[: corte + 1].strip())
            oracion = oracion[corte + 1 :].strip()
        if actual and len(actual) + 1 + len(oracion) > maximo:
            trozos.append(actual)
            actual = oracion
        else:
            actual = f"{actual} {oracion}".strip()
    if actual:
        trozos.append(actual)
    return trozos


def responder(datos: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(datos, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class Voz:
    def __init__(self, carpeta: Path, gpu: bool) -> None:
        import torch
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import Xtts

        self.torch = torch
        self.usar_gpu = gpu and torch.cuda.is_available()
        cfg = XttsConfig()
        cfg.load_json(str(carpeta / "config.json"))
        self.modelo = Xtts.init_from_config(cfg)
        self.modelo.load_checkpoint(cfg, checkpoint_dir=str(carpeta), use_deepspeed=False)
        self.modelo.eval()
        if self.modelo.speaker_manager is None:
            raise RuntimeError(f"Falta speakers_xtts.pth en {carpeta}")
        self.sample_rate = int(cfg.audio.output_sample_rate)

    def voces(self) -> list[str]:
        return sorted(self.modelo.speaker_manager.speakers)

    def _sintetizar(self, trozos: list[str], speaker: str, idioma: str, dispositivo: str) -> Any:
        import numpy as np

        torch = self.torch
        self.modelo.to(dispositivo)
        # Igual que Xtts.synthesize: (gpt_cond_latent, speaker_embedding) de la voz incluida.
        latente, embedding = list(self.modelo.speaker_manager.speakers[speaker].values())[:2]
        latente, embedding = latente.to(dispositivo), embedding.to(dispositivo)
        cfg = self.modelo.config
        ajustes = {
            "temperature": cfg.temperature,
            "length_penalty": cfg.length_penalty,
            "repetition_penalty": cfg.repetition_penalty,
            "top_k": cfg.top_k,
            "top_p": cfg.top_p,
        }
        pausa = np.zeros(int(PAUSA_S * self.sample_rate), dtype=np.float32)
        partes = []
        with torch.inference_mode():
            for trozo in trozos:
                salida = self.modelo.inference(trozo, idioma, latente, embedding, **ajustes)
                partes += [np.asarray(salida["wav"], dtype=np.float32), pausa]
        return np.concatenate(partes) if partes else np.zeros(0, dtype=np.float32)

    def narrar(self, texto: str, salida: Path, speaker: str, idioma: str) -> dict[str, Any]:
        import soundfile as sf

        torch = self.torch
        if speaker not in self.modelo.speaker_manager.speakers:
            raise ValueError(f"Voz '{speaker}' no existe. Opciones: {', '.join(self.voces())}")
        trozos = fragmentos(texto)
        inicio = time.perf_counter()
        en_gpu = self.usar_gpu
        try:
            wav = self._sintetizar(trozos, speaker, idioma, "cuda" if en_gpu else "cpu")
        except torch.cuda.OutOfMemoryError:
            en_gpu = False  # la GPU no alcanzó: esta escena en CPU
            self.modelo.to("cpu")
            torch.cuda.empty_cache()
            wav = self._sintetizar(trozos, speaker, idioma, "cpu")
        finally:
            if self.usar_gpu:  # la GPU queda libre para el resto de la historia
                self.modelo.to("cpu")
                torch.cuda.empty_cache()
        salida.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(salida), wav, self.sample_rate, subtype="PCM_16")
        return {
            "ok": True,
            "segundos": round(time.perf_counter() - inicio, 3),
            "duracion_s": round(len(wav) / self.sample_rate, 3),
            "sample_rate": self.sample_rate,
            "gpu": en_gpu,
            "fragmentos": len(trozos),
        }


def main(argv: list[str] | None = None) -> int:
    # La app lo arranca con "python -I" (ignora PYTHONIOENCODING): UTF-8 explícito.
    for flujo in (sys.stdin, sys.stdout):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if callable(reconfigurar):
            reconfigurar(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Proceso de voz XTTS-v2 de StoryBook")
    parser.add_argument("--modelo", type=Path, required=True, help="Carpeta de coqui/XTTS-v2")
    parser.add_argument("--cpu", action="store_true", help="No usar la GPU")
    parser.add_argument("--voces", action="store_true", help="Listar las voces y salir")
    args = parser.parse_args(argv)
    inicio = time.perf_counter()
    try:
        voz = Voz(args.modelo, gpu=not args.cpu)
    except Exception as exc:
        responder({"listo": False, "error": f"{type(exc).__name__}: {exc}"})
        traceback.print_exc(file=sys.stderr)
        return 1
    if args.voces:
        sys.stdout.write("\n".join(voz.voces()) + "\n")
        return 0
    responder(
        {
            "listo": True,
            "segundos_carga": round(time.perf_counter() - inicio, 3),
            "gpu": voz.usar_gpu,
            "sample_rate": voz.sample_rate,
            "voces": len(voz.voces()),
        }
    )
    for linea in sys.stdin:
        if not linea.strip():
            continue
        try:
            pedido = json.loads(linea)
            if pedido.get("cmd") == "salir":
                responder({"ok": True, "adios": True})
                return 0
            if pedido.get("cmd") != "narrar":
                raise ValueError(f"Comando desconocido: {pedido.get('cmd')}")
            respuesta = voz.narrar(
                str(pedido["texto"]),
                Path(pedido["salida"]),
                str(pedido.get("speaker") or "Ana Florence"),
                str(pedido.get("idioma") or "es"),
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            respuesta = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        responder(respuesta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
