"""Indexing profile controls for batch ingestion volume."""

from dataclasses import dataclass
from typing import Literal

IndexingProfileName = Literal["curated", "balanced", "comprehensive"]


@dataclass(frozen=True)
class IndexingProfile:
    name: IndexingProfileName
    label: str
    min_quality_score: float
    small_repo_budget: int | None
    medium_repo_budget: int | None
    large_repo_budget: int | None
    guidance: str

    def budget_for_chunks(self, chunk_count: int) -> int | None:
        if chunk_count <= 100:
            return self.small_repo_budget
        if chunk_count <= 300:
            return self.medium_repo_budget
        return self.large_repo_budget


INDEXING_PROFILES: dict[IndexingProfileName, IndexingProfile] = {
    "curated": IndexingProfile(
        name="curated",
        label="Curated",
        min_quality_score=0.8,
        small_repo_budget=25,
        medium_repo_budget=50,
        large_repo_budget=100,
        guidance=(
            "Only save high-signal, broadly reusable architecture or implementation "
            "patterns. Reject routine helpers, one-off business logic, thin wrappers, "
            "and examples that are obvious without context."
        ),
    ),
    "balanced": IndexingProfile(
        name="balanced",
        label="Balanced",
        min_quality_score=0.65,
        small_repo_budget=50,
        medium_repo_budget=100,
        large_repo_budget=200,
        guidance=(
            "Save reusable patterns with clear adaptation value. Be selective about "
            "common utilities and tests unless the implementation is notably complete."
        ),
    ),
    "comprehensive": IndexingProfile(
        name="comprehensive",
        label="Comprehensive",
        min_quality_score=0.5,
        small_repo_budget=100,
        medium_repo_budget=250,
        large_repo_budget=500,
        guidance=(
            "Capture most reusable candidates, while still rejecting plain glue code, "
            "duplicated snippets, and code that lacks a reusable lesson."
        ),
    ),
}

DEFAULT_INDEXING_PROFILE: IndexingProfileName = "curated"


def get_indexing_profile(name: str | None) -> IndexingProfile:
    normalized = (name or DEFAULT_INDEXING_PROFILE).lower()
    if normalized not in INDEXING_PROFILES:
        allowed = ", ".join(INDEXING_PROFILES)
        raise ValueError(f"Unknown indexing profile '{name}'. Expected one of: {allowed}")
    return INDEXING_PROFILES[normalized]  # type: ignore[index]
