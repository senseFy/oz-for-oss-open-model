from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import conftest  # noqa: F401

from oz.review_validation import (
    build_diff_maps_from_annotated_diff,
    normalize_review_payload,
    validate_review_payload,
)


ANNOTATED_DIFF = """diff --git a/src/example.py b/src/example.py
--- a/src/example.py
+++ b/src/example.py
@@ -1,3 +1,4 @@
[OLD:1,NEW:1] def greet():
[OLD:2]     return "hello"
[NEW:2]     name = "world"
[NEW:3]     return f"hello {name}"
[OLD:3,NEW:4] 
"""

DELETED_FILE_ANNOTATED_DIFF = """diff --git a/src/obsolete.py b/src/obsolete.py
--- a/src/obsolete.py
+++ /dev/null
@@ -1,2 +0,0 @@
[OLD:1] def obsolete():
[OLD:2]     return True
"""


class ReviewValidationTest(unittest.TestCase):
    def test_validates_comments_against_annotated_diff(self) -> None:
        diff_line_map, diff_content_map = build_diff_maps_from_annotated_diff(
            ANNOTATED_DIFF
        )
        result = validate_review_payload(
            {
                "body": "ok",
                "comments": [
                    {
                        "path": "src/example.py",
                        "line": 2,
                        "side": "RIGHT",
                        "body": "⚠️ [IMPORTANT] Use a less generic name.",
                    }
                ],
            },
            diff_line_map,
            diff_content_map,
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.comments), 1)
        self.assertEqual(result.body, "ok")

    def test_accepts_github_shaped_multiline_comments_with_start_side(self) -> None:
        diff_line_map, diff_content_map = build_diff_maps_from_annotated_diff(
            ANNOTATED_DIFF
        )
        result = validate_review_payload(
            {
                "body": "ok",
                "comments": [
                    {
                        "path": "src/example.py",
                        "start_line": 2,
                        "start_side": "RIGHT",
                        "line": 3,
                        "side": "RIGHT",
                        "body": "💡 [SUGGESTION] Combine these lines.",
                    }
                ],
            },
            diff_line_map,
            diff_content_map,
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(
            result.comments[0],
            {
                "path": "src/example.py",
                "start_line": 2,
                "start_side": "RIGHT",
                "line": 3,
                "side": "RIGHT",
                "body": "💡 [SUGGESTION] Combine these lines.",
            },
        )

    def test_requires_start_side_for_multiline_comments(self) -> None:
        diff_line_map, diff_content_map = build_diff_maps_from_annotated_diff(
            ANNOTATED_DIFF
        )
        result = validate_review_payload(
            {
                "body": "ok",
                "comments": [
                    {
                        "path": "src/example.py",
                        "start_line": 2,
                        "line": 3,
                        "side": "RIGHT",
                        "body": "💡 [SUGGESTION] Combine these lines.",
                    }
                ],
            },
            diff_line_map,
            diff_content_map,
        )
        self.assertEqual(len(result.errors), 1)
        self.assertIn("missing `start_side`", result.errors[0])

    def test_rejects_comments_for_lines_not_in_annotated_diff(self) -> None:
        diff_line_map, diff_content_map = build_diff_maps_from_annotated_diff(
            ANNOTATED_DIFF
        )
        result = validate_review_payload(
            {
                "summary": "ok",
                "comments": [
                    {
                        "path": "src/example.py",
                        "line": 99,
                        "side": "RIGHT",
                        "body": "⚠️ [IMPORTANT] This line is not present.",
                    }
                ],
            },
            diff_line_map,
            diff_content_map,
        )
        self.assertEqual(len(result.errors), 1)
        self.assertIn("not commentable", result.errors[0])

    def test_normalize_review_payload_drops_invalid_comments(self) -> None:
        diff_line_map, diff_content_map = build_diff_maps_from_annotated_diff(
            ANNOTATED_DIFF
        )
        _summary, comments = normalize_review_payload(
            {
                "summary": "ok",
                "comments": [
                    {
                        "path": "src/example.py",
                        "line": 2,
                        "side": "RIGHT",
                        "body": "⚠️ [IMPORTANT] Valid.",
                    },
                    {
                        "path": "src/example.py",
                        "line": 99,
                        "side": "RIGHT",
                        "body": "⚠️ [IMPORTANT] Invalid.",
                    },
                ],
            },
            diff_line_map,
            diff_content_map,
        )
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["line"], 2)

    def test_validates_left_comments_on_deleted_files(self) -> None:
        diff_line_map, diff_content_map = build_diff_maps_from_annotated_diff(
            DELETED_FILE_ANNOTATED_DIFF
        )
        result = validate_review_payload(
            {
                "summary": "ok",
                "comments": [
                    {
                        "path": "src/obsolete.py",
                        "line": 2,
                        "side": "LEFT",
                        "body": "⚠️ [IMPORTANT] Keep this behavior elsewhere.",
                    }
                ],
            },
            diff_line_map,
            diff_content_map,
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.comments), 1)

    def test_cli_validator_fails_for_invalid_inline_location(self) -> None:
        script = (
            Path(__file__).resolve().parent.parent
            / ".agents"
            / "skills"
            / "review-pr"
            / "scripts"
            / "validate_review_json.py"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            diff_path = tmp_path / "pr_diff.txt"
            review_path = tmp_path / "review.json"
            diff_path.write_text(ANNOTATED_DIFF, encoding="utf-8")
            review_path.write_text(
                json.dumps(
                    {
                        "verdict": "REJECT",
                        "body": "bad",
                        "comments": [
                            {
                                "path": "src/example.py",
                                "line": 99,
                                "side": "RIGHT",
                                "body": "⚠️ [IMPORTANT] Invalid.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--review-json",
                    str(review_path),
                    "--diff",
                    str(diff_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("not commentable", completed.stderr)


if __name__ == "__main__":
    unittest.main()
