"""GlassMatch: open-source optical glass selection & material database."""
from glassmatch.database import GlassDatabase, load_default_database
from glassmatch.matching import normalize_weights, score_glass, match_glasses
from glassmatch.validation import validate_property_frame, validate_glass_frame

__all__ = [
    "GlassDatabase",
    "load_default_database",
    "normalize_weights",
    "score_glass",
    "match_glasses",
    "validate_property_frame",
    "validate_glass_frame",
]
__version__ = "0.2.0"
