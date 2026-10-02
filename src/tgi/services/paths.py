"""The boundary between a received value and a disk path.

Every identifier that reaches a filesystem operation passes through here. The module
exists because the alternative, validating at each call site, is a rule nobody can
enforce: a route added later simply forgets it, and the class reopens in silence.

Two kinds of guard live here, and they are not interchangeable. `safe_basename` keeps
a name *inside* a directory by throwing away everything before the last separator;
the `validated_*` functions *reject* a value outright. A name is sanitised because the
user is entitled to one; an identifier is refused because a wrong one means nothing.
"""

from __future__ import annotations

import re
import unicodedata

# Windows refuses these, with or without an extension, whatever the case. Reading one
# through a synchronous open blocks the event loop for the whole server, so they are
# renamed rather than rejected: the upload is legitimate, its name is not.
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{d}" for d in "123456789"}
    | {f"lpt{d}" for d in "123456789"}
    # Windows resolves the superscript forms to the same devices
    | {f"com{s}" for s in "\u00b9\u00b2\u00b3"}
    | {f"lpt{s}" for s in "\u00b9\u00b2\u00b3"}
)

# A blacklist, not a whitelist: a whitelist of [A-Za-z0-9._-] plus Unicode letters would
# reject the emoji of "specification_ete_<emoji>.docx", which is category So and perfectly
# legitimate. Containment comes from taking the basename, never from the character class.
_FORBIDDEN_IN_NAME = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")

_FALLBACK_NAME = "document"

_PROJECT_ID = re.compile(r"[0-9a-f-]{12,36}")
_VERSION = re.compile(r"v[1-9][0-9]*")
# Rejects "..", and rejects a leading dot so a hidden file cannot be addressed. Dots stay
# legal inside, wider than the schema's ^TEST-[0-9]+$, so a hand-written id still resolves.
_TEST_ID = re.compile(r"(?!\.+$)[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}")


class InvalidIdentifier(ValueError):
    """A received identifier cannot address anything on disk.

    Inherits from ValueError and nothing else. Were it a FileNotFoundError, the callers
    that already catch that one would swallow a refused identifier and report it as a
    missing project, which is the same answer for two very different facts.
    """

    __slots__ = ()


def safe_basename(raw: str) -> str:
    """Reduce a client-supplied filename to something that cannot leave its directory.

    Basename first, sanitising second: that order is what makes "../../../etc/passwd.md"
    become "passwd.md" rather than "etc_passwd.md". Flattening the separators instead
    would keep the traversal in the name and only defer the problem.
    """
    # Both separators, because a Windows client sends the one its OS uses
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    # NTFS ignores trailing dots and spaces, so ".. " addresses "..": strip before judging
    name = unicodedata.normalize("NFC", name.rstrip(" ."))
    name = _FORBIDDEN_IN_NAME.sub("_", name)
    if name.split(".", 1)[0].casefold() in _WINDOWS_RESERVED:
        name = f"_{name}"
    # Stated as "nothing left but dots or underscores" rather than listing "." and "..",
    # because the enumeration silently let "..." through
    return _FALLBACK_NAME if not name.strip("._") else name


def validated_project_id(raw: str) -> str:
    """Return the project id, or refuse it before it can compose a path.

    The pattern spans 12 to 36 characters because existing projects carry a uuid4 while
    newer ones are shorter; narrowing it to either would make the other unreachable, which
    is a behaviour change and not hardening.
    """
    if not _PROJECT_ID.fullmatch(raw):
        raise InvalidIdentifier(raw)
    return raw


def is_project_id(raw: str) -> bool:
    """Whether a name is a project identifier, for filtering rather than refusing.

    Listing a directory is not the same act as answering a request: an entry whose name is
    not an identifier is simply not a project, which is not an error anyone should see.
    """
    return _PROJECT_ID.fullmatch(raw) is not None


def validated_version(raw: str) -> str:
    """Return the version id, or refuse it before it can compose a path."""
    if not _VERSION.fullmatch(raw):
        raise InvalidIdentifier(raw)
    return raw


def validated_test_id(raw: str) -> str:
    """Return the test id, or refuse it before it can compose a path."""
    if not _TEST_ID.fullmatch(raw):
        raise InvalidIdentifier(raw)
    return raw
