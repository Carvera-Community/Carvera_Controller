"""Reference screenshot paths and policies for visual regression tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

VISUAL_TEST_DIR = Path(__file__).resolve().parent
COMMITTED_REFERENCE_DIR = VISUAL_TEST_DIR / "reference"
LOCAL_REFERENCE_DIR = VISUAL_TEST_DIR / "local-reference"

VisualReferenceMode = Literal["local", "committed"]


@dataclass(frozen=True)
class VisualReferenceConfig:
    mode: VisualReferenceMode
    reference_dir: Path
    update: bool

    def reference_path(self, name: str) -> Path:
        return self.reference_dir / f"{name}.png"

    def skip_if_missing(self, name: str) -> None:
        if self.update or self.reference_path(name).exists():
            return
        if self.mode == "local":
            pytest.skip(
                f"No local reference screenshot for '{name}'. "
                "Run with --update-references --visual-reference-mode=local to create one."
            )
        raise FileNotFoundError(
            f"No committed reference screenshot for '{name}'. "
            "Run the container update command to create committed references."
        )


def create_visual_reference_config(mode: str, update: bool) -> VisualReferenceConfig:
    if mode == "local":
        return VisualReferenceConfig(mode="local", reference_dir=LOCAL_REFERENCE_DIR, update=update)
    if mode == "committed":
        return VisualReferenceConfig(mode="committed", reference_dir=COMMITTED_REFERENCE_DIR, update=update)
    raise ValueError(f"Unknown visual reference mode: {mode}")
