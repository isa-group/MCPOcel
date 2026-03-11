from enum import Enum
from typing import Dict
from shared.config.env import Env

class ExtractionProfile(Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    COMPLETE = "complete"

# Settings
PROFILES: Dict[ExtractionProfile, Dict[str, bool]] = {
    ExtractionProfile.MINIMAL: {
        "withReviews": False,
        "withReviewComments": False,
        "withThreads": False,
        "withTimeline": False,
        "withStatusChecks": False,
        "withDiscussions": True,
        "withFileObjects": False,
    },
    ExtractionProfile.STANDARD: {
        "withReviews": True,           # Reviews
        "withReviewComments": False,   # Line-by-line comments
        "withThreads": False,
        "withTimeline": True,          # Timeline
        "withStatusChecks": True,      # CI
        "withDiscussions": True,
        "withFileObjects": False,
    },
    ExtractionProfile.COMPLETE: {
        "withReviews": True,
        "withReviewComments": True,    # Maximum granularity
        "withThreads": True,
        "withTimeline": True,
        "withStatusChecks": True,
        "withDiscussions": True,
        "withFileObjects": True,       # REST file enrichment per commit (COMPLETE only)
    }
}

def get_profile_vars(profile_name: str = "standard") -> Dict[str, bool]:
    """Returns the GraphQL variables for the requested profile."""
    try:
        selected = ExtractionProfile(profile_name.lower())
    except ValueError:
        selected = ExtractionProfile.STANDARD

    return PROFILES[selected]


def get_profile_from_env() -> ExtractionProfile:
    """Reads EXTRACTION_PROFILE from environment, defaults to STANDARD."""
    name = Env.optional_str("EXTRACTION_PROFILE", default="standard")
    try:
        return ExtractionProfile(name.lower())
    except ValueError:
        return ExtractionProfile.STANDARD