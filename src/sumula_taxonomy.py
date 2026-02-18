"""Versioned taxonomy for admissibility súmulas (STJ/STF)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SumulaTaxonomy(BaseModel):
    """Canonical versioned source for allowed súmulas."""

    version: str
    source: str
    stj: set[int] = Field(default_factory=set)
    stf: set[int] = Field(default_factory=set)

    @property
    def validas(self) -> set[int]:
        """Return full allowed set."""
        return set(self.stj) | set(self.stf)


CURRENT_SUMULA_TAXONOMY = SumulaTaxonomy(
    version="2026.02.13",
    source="STJ/STF taxonomia interna homologada",
    stj={5, 7, 13, 83, 126, 211, 518},
    stf={279, 280, 281, 282, 283, 284, 356, 735},
)

SUMULAS_TAXONOMY_VERSION = CURRENT_SUMULA_TAXONOMY.version
SUMULAS_TAXONOMY_SOURCE = CURRENT_SUMULA_TAXONOMY.source
SUMULAS_STJ = set(CURRENT_SUMULA_TAXONOMY.stj)
SUMULAS_STF = set(CURRENT_SUMULA_TAXONOMY.stf)
SUMULAS_VALIDAS = CURRENT_SUMULA_TAXONOMY.validas

