"""Métricas de consistencia visual con OpenCLIP (CPU).

* Similitud imagen-imagen: coseno entre embeddings de dos ilustraciones. Entre escenas de
  una misma historia, valores altos indican personaje y estilo reconocibles.
* Similitud imagen-texto (CLIPScore sin reescalar): coseno entre la imagen y su prompt.
  Indica si la ilustración corresponde a lo que pide la escena.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from pathlib import Path
from statistics import mean

from PIL import Image


class ClipMetricsError(Exception):
    """Errores al cargar OpenCLIP o calcular similitudes."""


class ClipScorer:
    def __init__(self, modelo: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k") -> None:
        import open_clip
        import torch

        self._torch = torch
        self.modelo, _, self.preprocess = open_clip.create_model_and_transforms(
            modelo, pretrained=pretrained, device="cpu"
        )
        self.modelo.eval()
        self.tokenizer = open_clip.get_tokenizer(modelo)

    def _embed_imagenes(self, rutas: list[Path]):  # -> torch.Tensor
        torch = self._torch
        lote = torch.stack([self.preprocess(Image.open(r).convert("RGB")) for r in rutas])
        with torch.no_grad():
            emb = self.modelo.encode_image(lote)
        return emb / emb.norm(dim=-1, keepdim=True)

    def _embed_textos(self, textos: list[str]):  # -> torch.Tensor
        torch = self._torch
        with torch.no_grad():
            emb = self.modelo.encode_text(self.tokenizer(textos))
        return emb / emb.norm(dim=-1, keepdim=True)

    def similitudes(
        self, imagenes: Sequence[Image.Image | Path], textos: Sequence[str]
    ) -> list[list[float]]:
        """Coseno de cada imagen con cada texto (filas: imágenes; columnas: textos).

        Lo usa la elección de la mejor versión de una ilustración (``image.seleccion``).
        """
        torch = self._torch
        pil = [i if isinstance(i, Image.Image) else Image.open(i) for i in imagenes]
        lote = torch.stack([self.preprocess(i.convert("RGB")) for i in pil])
        with torch.no_grad():
            emb = self.modelo.encode_image(lote)
        emb = emb / emb.norm(dim=-1, keepdim=True)
        sims = emb @ self._embed_textos(list(textos)).T
        return [[round(float(x), 4) for x in fila] for fila in sims.tolist()]

    def imagen_texto(self, imagen: Path, texto: str) -> float:
        sim = (self._embed_imagenes([imagen]) @ self._embed_textos([texto]).T).item()
        return round(float(sim), 4)

    def imagen_imagen(self, rutas: list[Path]) -> dict[str, float]:
        """Media y mínimo de la similitud por pares (requiere al menos 2 imágenes)."""
        if len(rutas) < 2:
            raise ClipMetricsError("Se necesitan al menos 2 imágenes")
        emb = self._embed_imagenes(rutas)
        sims = [float((emb[i] @ emb[j]).item()) for i, j in combinations(range(len(rutas)), 2)]
        return {"media": round(mean(sims), 4), "minimo": round(min(sims), 4), "pares": len(sims)}
