"""Load and parse ownership-area definitions from ``warpdotdev/warp-ownership``.

The repo contains one markdown file per team under ``ownership-areas/``. Each
file is a series of ``### Area`` headings followed by ``- **Owners**:`` and
``- **Matches**:`` bullets describing the area's GitHub-handle owners and a
free-form description of what behavior the area covers.

This module mirrors the shape of the STAKEHOLDERS helpers in
:mod:`oz.triage` so the Vercel control plane can pull the area definitions
via the GitHub App installation token already minted by
:func:`core.github_app.fetch_installation_token`, render them into the PR
review prompt, and deterministically map the agent's chosen area back to a
reviewer at apply time.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from github.GithubException import GithubException, UnknownObjectException

from .triage import decode_repo_text_file

logger = logging.getLogger(__name__)

# Directory inside ``warpdotdev/warp-ownership`` that holds the per-team
# markdown files. Mirrors the layout established by the repo's README.
OWNERSHIP_AREAS_DIR = "ownership-areas"

# Default repo slug the control plane reads ownership areas from. The
# Vercel runtime can override via ``WARP_OWNERSHIP_REPO`` if a fork uses
# a different slug.
DEFAULT_OWNERSHIP_REPO = "warpdotdev/warp-ownership"

# Pattern for the area heading. ``###`` followed by the area name.
_AREA_HEADING_RE = re.compile(r"^###\s+(?P<name>.+?)\s*$")
# Pattern for the owners bullet. Matches the start of a markdown list item
# whose bold key is ``Owners`` (case-insensitive). The owner tokens are
# extracted from the remainder via ``_OWNER_HANDLE_RE``.
_OWNERS_BULLET_RE = re.compile(
    r"^\s*[-*]\s*\*\*Owners\*\*:\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
# Pattern for the matches bullet.
_MATCHES_BULLET_RE = re.compile(
    r"^\s*[-*]\s*\*\*Matches\*\*:\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
# Owner handles appear as ``@login`` separated by commas. Anything that
# does not start with ``@`` (e.g. ``<TODO: resolve handle>``) is ignored
# so partial entries in the markdown do not break the parse.
_OWNER_HANDLE_RE = re.compile(r"@([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)")


@dataclass(frozen=True)
class OwnershipArea:
    """A single ``### Area`` entry parsed from an ownership-areas file.

    ``name`` is the heading text exactly as it appears in the markdown
    (case-sensitive). ``owners`` is the list of GitHub logins extracted
    from the ``**Owners**:`` bullet, with the leading ``@`` stripped.
    ``matches`` is the prose description from the ``**Matches**:`` bullet.
    """

    name: str
    owners: list[str]
    matches: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for ``RunState.payload_subset``."""
        return {"name": self.name, "owners": list(self.owners), "matches": self.matches}


def _parse_owner_handles(value: str) -> list[str]:
    """Extract GitHub logins from an ``Owners`` bullet value.

    Accepts a comma-separated list of ``@login`` tokens. Returns the
    handles in the order they appear, deduplicated while preserving
    order. Non-``@`` tokens (e.g. ``<TODO: resolve handle>`` placeholders)
    are silently skipped so partial markdown entries do not break the
    parse.
    """
    seen: set[str] = set()
    owners: list[str] = []
    for match in _OWNER_HANDLE_RE.finditer(value or ""):
        handle = match.group(1)
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        owners.append(handle)
    return owners


def _parse_ownership_area_file(text: str) -> list[OwnershipArea]:
    """Parse a single ownership-area markdown file into structured entries.

    Walks the file line by line. Each ``### Area`` heading opens a new
    block. Owners and matches bullets within that block are collected
    until the next heading or EOF. Areas without at least one owner are
    dropped so consumers do not have to handle empty owner lists.
    """
    areas: list[OwnershipArea] = []
    current_name: str | None = None
    current_owners: list[str] = []
    current_matches: str = ""

    def flush() -> None:
        nonlocal current_name, current_owners, current_matches
        if current_name and current_owners:
            areas.append(
                OwnershipArea(
                    name=current_name,
                    owners=list(current_owners),
                    matches=current_matches,
                )
            )
        current_name = None
        current_owners = []
        current_matches = ""

    for raw_line in (text or "").splitlines():
        heading_match = _AREA_HEADING_RE.match(raw_line)
        if heading_match:
            flush()
            current_name = heading_match.group("name").strip()
            continue
        if current_name is None:
            continue
        owners_match = _OWNERS_BULLET_RE.match(raw_line)
        if owners_match:
            current_owners = _parse_owner_handles(owners_match.group("value"))
            continue
        matches_match = _MATCHES_BULLET_RE.match(raw_line)
        if matches_match:
            current_matches = matches_match.group("value").strip()
            continue
    flush()
    return areas


def load_ownership_areas_from_repo(repo_handle: Any) -> list[OwnershipArea]:
    """Load every ``ownership-areas/*.md`` file in *repo_handle*.

    Lists the contents of the ``ownership-areas/`` directory, decodes
    each ``.md`` file via :func:`oz.triage.decode_repo_text_file`, and
    concatenates the parsed area lists. Mirrors the fail-open posture of
    :func:`oz.triage.load_stakeholders_from_repo`: any GitHub API error
    or unexpected payload returns an empty list so non-member PR
    reviewer selection degrades to the STAKEHOLDERS fallback rather
    than aborting the dispatch.
    """
    try:
        contents = repo_handle.get_contents(OWNERSHIP_AREAS_DIR)
    except UnknownObjectException:
        return []
    except GithubException:
        logger.exception(
            "Failed to list %s in %s",
            OWNERSHIP_AREAS_DIR,
            getattr(repo_handle, "full_name", ""),
        )
        return []
    if not isinstance(contents, list):
        # ``ownership-areas`` resolved to a single file rather than a
        # directory; that is a configuration error from the host repo.
        return []
    areas: list[OwnershipArea] = []
    for entry in contents:
        path = str(getattr(entry, "path", "") or "")
        if not path.lower().endswith(".md"):
            continue
        text = decode_repo_text_file(repo_handle, path)
        if not text:
            continue
        areas.extend(_parse_ownership_area_file(text))
    return areas


def format_ownership_areas_for_prompt(areas: list[OwnershipArea]) -> str:
    """Render parsed ownership areas as a human-readable prompt block.

    The agent prompt shows ``owners`` for human inspection (so reviewers
    looking at the dispatched prompt can see the mapping), but the
    agent's job is purely to return one matching area name. Vercel
    re-derives the owners deterministically at apply time.
    """
    if not areas:
        return "No ownership areas configured."
    lines: list[str] = []
    for area in areas:
        owners = ", ".join(f"@{login}" for login in area.owners) or "(unassigned)"
        lines.append(f"- {area.name}")
        lines.append(f"  owners: {owners}")
        if area.matches:
            lines.append(f"  matches: {area.matches}")
    return "\n".join(lines)


def ownership_area_lookup(areas: list[OwnershipArea]) -> dict[str, list[str]]:
    """Return a ``name -> owners`` map keyed by canonical area name.

    Names are matched against the agent's ``recommended_area`` value
    case-sensitively. When two areas share a name the first occurrence
    wins; the duplicate is logged so the repo maintainer can resolve
    the ambiguity but the resolver remains deterministic.
    """
    lookup: dict[str, list[str]] = {}
    for area in areas:
        if area.name in lookup:
            logger.warning(
                "Duplicate ownership area name %r encountered while building lookup; "
                "ignoring later occurrence",
                area.name,
            )
            continue
        lookup[area.name] = list(area.owners)
    return lookup


__all__ = [
    "DEFAULT_OWNERSHIP_REPO",
    "OWNERSHIP_AREAS_DIR",
    "OwnershipArea",
    "format_ownership_areas_for_prompt",
    "load_ownership_areas_from_repo",
    "ownership_area_lookup",
]
