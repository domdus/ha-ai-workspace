from __future__ import annotations

import re

# A whole message that only greets or thanks. Anything else may need the house.
_SMALL_TALK = re.compile(
    r"""
    ^
    (?:
        (?:hi|hello|hey|hiya|howdy|yo|hallo|moin|servus|hola|ciao|huhu)
        (?:\s+(?:there|cursor))?
      | good\s+(?:morning|afternoon|evening|night)
      | guten\s+(?:morgen|tag|abend)
      | (?:thanks|thank\s+you|thx|ty|danke(?:\s*schoen|\s*schön)?|merci|cheers)
        (?:\s+(?:a\s+lot|so\s+much|sehr))?
      | (?:how\s+are\s+you|how'?s\s+it\s+going|what'?s\s+up|wie\s+geht(?:'?s|\s+es)?)
      | are\s+you\s+(?:ok(?:ay)?|alright|there)(?:\s+again)?
      | you\s+(?:ok(?:ay)?|alright)
      | (?:cursor|ping)
    )
    [\s!.?,]*
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def wants_house_tools(message: str) -> bool:
    """False only for a pure greeting or thanks. Short confirmations still need tools."""
    text = " ".join(str(message or "").split())
    if not text:
        return True
    return _SMALL_TALK.match(text) is None
