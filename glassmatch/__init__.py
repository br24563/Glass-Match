"""GlassMatch: open-source optical glass selection & material database."""
from glassmatch.database import GlassDatabase, load_default_database
from glassmatch.matching import normalize_weights, score_glass, match_glasses
from glassmatch.validation import validate_property_frame, validate_glass_frame
from glassmatch.equivalency import (EquivalencyCriteria, candidate_pairs,
                                    candidates_for, curated_equivalents)

__all__ = [
    "GlassDatabase",
    "load_default_database",
    "normalize_weights",
    "score_glass",
    "match_glasses",
    "validate_property_frame",
    "validate_glass_frame",
    "candidate_pairs",
    "candidates_for",
    "EquivalencyCriteria",
]
__version__ = "0.3.1"
