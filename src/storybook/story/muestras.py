"""Historias ya generadas que sirven de entrada a las pruebas reales de cada etapa."""

from __future__ import annotations

from pathlib import Path

from storybook.schemas import StoryBible


def elegir_story(raiz_f1: Path, modelo_llm: str) -> Path:
    """Primera Story Bible válida de la corrida más reciente de F1 hecha con ``modelo_llm``.

    Cada corrida guarda ``resumen.md`` con el modelo usado: así no se elige por error una
    historia del experimento con el 8B. La usan las pruebas reales de imagen, voz y sonido
    (``scripts/f2_f3_prueba.py`` y ``scripts/f4_sonido.py``), que así trabajan siempre sobre
    la misma historia.
    """
    if not raiz_f1.is_dir():
        raise FileNotFoundError(f"No existe {raiz_f1}. Ejecuta antes: setup_windows.ps1 -Paso f1")
    corridas = sorted((d for d in raiz_f1.iterdir() if d.is_dir()), reverse=True)
    for corrida in corridas:
        resumen = corrida / "resumen.md"
        if not resumen.is_file() or f"`{modelo_llm}`" not in resumen.read_text(encoding="utf-8"):
            continue
        for ruta in sorted(corrida.glob("story_*.json")):
            try:
                StoryBible.model_validate_json(ruta.read_text(encoding="utf-8"))
            except ValueError:
                continue
            return ruta
    raise FileNotFoundError(
        f"No hay historias válidas de F1 generadas con {modelo_llm} en {raiz_f1}. "
        "Ejecuta antes: setup_windows.ps1 -Paso f1"
    )
