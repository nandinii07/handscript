"""How a backend failure becomes an HTTP status and a message.

The backend raises a specific exception for every way a build can fail, and
the messages are already written for the person who has to fix the problem -
"Page 1 of 3 ... does not look like page 1: it ends with 2 unwritten box(es)"
tells a user exactly what to do. So the application maps by type and passes
the message through rather than replacing it with something vaguer.

The distinction that matters to a user is the status code: 4xx is something
they can fix by uploading different scans, 5xx is not their fault at all.
"""

import re
from typing import Tuple

from handwrite import (
    FontForgeFailed,
    FontForgeNotFound,
    NotationError,
    PotraceFailed,
    PotraceNotFound,
    SheetDetectionError,
)
from handwrite.sheettopng import PageValidationError

# Re-exported so route handlers can catch bad notation without importing the
# backend themselves. Naming backend exception types is this module's whole
# job; spreading that around would be how the boundary quietly disappears.
__all__ = [
    "NotationError",
    "ERROR_STATUS",
    "USER_FIXABLE",
    "status_for",
    "is_expected",
    "message_for",
]

# Ordered most specific first: PageValidationError is a SheetDetectionError,
# and both are 422, but being explicit keeps the intent visible.
ERROR_STATUS: Tuple[Tuple[type, int], ...] = (
    # The scans are wrong, and the message says how.
    (PageValidationError, 422),
    (SheetDetectionError, 422),
    # The request itself was wrong.
    (IsADirectoryError, 400),
    (FileNotFoundError, 400),
    (ValueError, 400),
    # The server is missing a tool it needs. Never the user's doing.
    (PotraceNotFound, 503),
    (FontForgeNotFound, 503),
    # The tools are there but the build broke.
    (PotraceFailed, 500),
    (FontForgeFailed, 500),
)

# Statuses the user can do something about; anything else is ours to fix.
USER_FIXABLE = (400, 422)


def status_for(error: BaseException) -> int:
    """Return the HTTP status for a backend exception, 500 if unrecognised."""
    for error_type, status in ERROR_STATUS:
        if isinstance(error, error_type):
            return status
    return 500


def is_expected(error: BaseException) -> bool:
    """Whether this is a failure mode the backend describes on purpose.

    Unexpected exceptions still become a 500, but they are logged as bugs
    rather than reported as though they were a known outcome.
    """
    return any(isinstance(error, error_type) for error_type, _ in ERROR_STATUS)


# The backend names the file it was reading, which is a server-side temporary
# path: meaningless to whoever uploaded the page, and not something to put on
# a web page. The name itself is worth keeping - it says which page went
# wrong - so only the directories are dropped.
_QUOTED_PATH = re.compile(r"'((?:[A-Za-z]:)?[\\/][^']*)'")


def _without_server_paths(message: str) -> str:
    """Replace any absolute path in a message with just its filename.

    Both separators, because the message may have been produced on either
    kind of host and this code has to read it on any other.
    """
    return _QUOTED_PATH.sub(
        lambda match: "'{}'".format(re.split(r"[\\/]", match.group(1))[-1]), message
    )


def message_for(error: BaseException) -> str:
    """The text to show the user.

    Expected failures keep the backend's own wording, which was written for
    the person who has to fix the problem - "does not look like page 1: it
    ends with 2 unwritten box(es)" is exactly what they need. Anything else
    gets a generic line, because an unexpected traceback is not something a
    user can act on and may say more about the server than it should.
    """
    if is_expected(error):
        return _without_server_paths(str(error))
    return "The font could not be built because of an unexpected problem."
