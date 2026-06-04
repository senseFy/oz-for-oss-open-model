"""Tests for the ``oz.ownership`` parser/loader helpers."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from github.GithubException import GithubException, UnknownObjectException

from . import conftest  # noqa: F401

from oz.ownership import (
    OwnershipArea,
    _parse_ownership_area_file,
    format_ownership_areas_for_prompt,
    load_ownership_areas_from_repo,
    ownership_area_lookup,
)


# Real-shape markdown snippets taken directly from
# warp-ownership/ownership-areas/app.md and platform.md so the parser is
# exercised against the format the consumers actually publish.
APP_SNIPPET = """# App

Ownership areas for the App team.

### Conversation and Session Restoration
- **Owners**: @seemeroland
- **Matches**: Restoring previous agent conversations, session persistence across restarts, conversation history loading

### MCP (Model Context Protocol)
- **Owners**: @peicodes, @vkodithala
- **Matches**: MCP server connections, MCP tools and resources, third-party integrations via MCP

### Grep tool call
- **Owners**: @vkodithala, @moirahuang, @szgupta
- **Matches**: UI for grep tool used by agent
"""

PLATFORM_SNIPPET = """# Platform

### Session Sharing
- **Owners**: @abhishekp106, @szgupta, @bnavetta
- **Matches**: Session sharing, agent session sharing, session sharing server

### Oz Webapp (NOT app.warp.dev)
- **Owners**: @Legoben
- **Matches**: Oz Webapp, oz.warp.dev, oz.staging.warp.dev
"""

class ParseOwnershipAreaFileTest(unittest.TestCase):
    def test_parses_app_snippet(self) -> None:
        areas = _parse_ownership_area_file(APP_SNIPPET)
        self.assertEqual(len(areas), 3)
        self.assertEqual(areas[0].name, "Conversation and Session Restoration")
        self.assertEqual(areas[0].owners, ["seemeroland"])
        self.assertIn(
            "Restoring previous agent conversations", areas[0].matches
        )
        self.assertEqual(areas[1].name, "MCP (Model Context Protocol)")
        self.assertEqual(areas[1].owners, ["peicodes", "vkodithala"])
        self.assertEqual(
            areas[2].owners, ["vkodithala", "moirahuang", "szgupta"]
        )

    def test_parses_platform_snippet(self) -> None:
        areas = _parse_ownership_area_file(PLATFORM_SNIPPET)
        self.assertEqual(len(areas), 2)
        self.assertEqual(areas[0].name, "Session Sharing")
        self.assertEqual(
            areas[0].owners, ["abhishekp106", "szgupta", "bnavetta"]
        )
        # Heading text with punctuation is preserved verbatim so the
        # apply step can match the agent's ``recommended_area`` exactly.
        self.assertEqual(areas[1].name, "Oz Webapp (NOT app.warp.dev)")

    def test_ignores_text_before_first_heading(self) -> None:
        text = "Some preamble\n\nAnd more text\n\n### Real Area\n- **Owners**: @alice\n- **Matches**: x\n"
        areas = _parse_ownership_area_file(text)
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0].name, "Real Area")

    def test_returns_empty_for_empty_text(self) -> None:
        self.assertEqual(_parse_ownership_area_file(""), [])
        self.assertEqual(_parse_ownership_area_file("# Just a heading\n"), [])

    def test_owners_bullet_is_case_insensitive(self) -> None:
        text = "### Area\n- **owners**: @alice\n- **matches**: x\n"
        areas = _parse_ownership_area_file(text)
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0].owners, ["alice"])

    def test_dedupes_owner_handles_within_an_area(self) -> None:
        text = "### Area\n- **Owners**: @alice, @ALICE, @bob\n- **Matches**: x\n"
        areas = _parse_ownership_area_file(text)
        self.assertEqual(areas[0].owners, ["alice", "bob"])

    def test_ignores_handles_inside_angle_bracketed_emails(self) -> None:
        text = (
            "### Area\n"
            "- **Owners**: @alice <alice@warp.dev>, @bob <bob@warp.dev>\n"
            "- **Matches**: x\n"
        )
        areas = _parse_ownership_area_file(text)
        self.assertEqual(areas[0].owners, ["alice", "bob"])


class LoadOwnershipAreasFromRepoTest(unittest.TestCase):
    def _make_repo(
        self,
        *,
        listing: list[MagicMock] | None = None,
        file_contents: dict[str, str] | None = None,
    ) -> MagicMock:
        repo = MagicMock()
        repo.full_name = "warpdotdev/warp-ownership"

        def get_contents(path: str) -> Any:
            if path == "ownership-areas":
                if listing is None:
                    raise UnknownObjectException(404, {}, {})
                return listing
            content_obj = MagicMock()
            content_obj.decoded_content = (file_contents or {}).get(
                path, ""
            ).encode("utf-8")
            return content_obj

        repo.get_contents.side_effect = get_contents
        return repo

    def _file_entry(self, path: str) -> MagicMock:
        entry = MagicMock()
        entry.path = path
        return entry

    def test_loads_and_concatenates_per_team_files(self) -> None:
        repo = self._make_repo(
            listing=[
                self._file_entry("ownership-areas/app.md"),
                self._file_entry("ownership-areas/platform.md"),
            ],
            file_contents={
                "ownership-areas/app.md": APP_SNIPPET,
                "ownership-areas/platform.md": PLATFORM_SNIPPET,
            },
        )
        areas = load_ownership_areas_from_repo(repo)
        names = [area.name for area in areas]
        self.assertEqual(
            names,
            [
                "Conversation and Session Restoration",
                "MCP (Model Context Protocol)",
                "Grep tool call",
                "Session Sharing",
                "Oz Webapp (NOT app.warp.dev)",
            ],
        )

    def test_skips_non_markdown_files(self) -> None:
        repo = self._make_repo(
            listing=[
                self._file_entry("ownership-areas/README.txt"),
                self._file_entry("ownership-areas/app.md"),
            ],
            file_contents={"ownership-areas/app.md": APP_SNIPPET},
        )
        areas = load_ownership_areas_from_repo(repo)
        self.assertEqual(len(areas), 3)

    def test_returns_empty_when_directory_missing(self) -> None:
        repo = self._make_repo(listing=None)
        self.assertEqual(load_ownership_areas_from_repo(repo), [])

    def test_returns_empty_on_github_exception(self) -> None:
        repo = MagicMock()
        repo.full_name = "warpdotdev/warp-ownership"
        repo.get_contents.side_effect = GithubException(500, {}, {})
        self.assertEqual(load_ownership_areas_from_repo(repo), [])

    def test_returns_empty_when_path_is_a_file(self) -> None:
        # ``get_contents`` returns a single object when the path points
        # at a file rather than a directory; treat that as misconfigured
        # and return an empty list.
        repo = MagicMock()
        repo.full_name = "warpdotdev/warp-ownership"
        repo.get_contents.return_value = MagicMock()
        self.assertEqual(load_ownership_areas_from_repo(repo), [])


class OwnershipAreaLookupTest(unittest.TestCase):
    def test_returns_name_to_owners_map(self) -> None:
        areas = [
            OwnershipArea(name="Alpha", owners=["a", "b"], matches=""),
            OwnershipArea(name="Beta", owners=["c"], matches="prose"),
        ]
        lookup = ownership_area_lookup(areas)
        self.assertEqual(lookup, {"Alpha": ["a", "b"], "Beta": ["c"]})

    def test_first_occurrence_wins_for_duplicate_names(self) -> None:
        areas = [
            OwnershipArea(name="Same", owners=["first"], matches=""),
            OwnershipArea(name="Same", owners=["second"], matches=""),
        ]
        lookup = ownership_area_lookup(areas)
        self.assertEqual(lookup, {"Same": ["first"]})


class FormatOwnershipAreasForPromptTest(unittest.TestCase):
    def test_renders_owners_and_matches(self) -> None:
        areas = [
            OwnershipArea(
                name="MCP (Model Context Protocol)",
                owners=["peicodes", "vkodithala"],
                matches="MCP server connections, MCP tools and resources",
            )
        ]
        rendered = format_ownership_areas_for_prompt(areas)
        self.assertIn("- MCP (Model Context Protocol)", rendered)
        self.assertIn("owners: @peicodes, @vkodithala", rendered)
        self.assertIn("matches: MCP server connections", rendered)

    def test_empty_areas_produces_placeholder(self) -> None:
        self.assertEqual(
            format_ownership_areas_for_prompt([]),
            "No ownership areas configured.",
        )


if __name__ == "__main__":
    unittest.main()
