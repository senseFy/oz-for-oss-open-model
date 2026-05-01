#!/usr/bin/env python3
"""Validate a review.json artifact against an annotated PR diff.

This script is intended to run inside the review-pr skill before uploading
``review.json``. It imports the same validation helpers the control plane uses
before calling GitHub's ``create_review`` API so malformed inline locations are
caught while the agent can still fix the artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _bootstrap_repo_imports() -> None:
    """Make the workflow repo importable when running this bundled script."""
    script_path = Path(__file__).resolve()
    for parent in script_path.parents:
        if (parent / "oz" / "review_validation.py").is_file():
            sys.path.insert(0, str(parent))
            return


_bootstrap_repo_imports()

from oz.review_validation import (  # noqa: E402
    build_diff_maps_from_annotated_diff,
    validate_review_payload,
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"review validation failed: {path} does not exist")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"review validation failed: {path} is invalid JSON: {exc}")


def _validate_verdict(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["review.json must decode to a JSON object."]
    verdict = payload.get("verdict")
    if verdict not in {"APPROVE", "REJECT"}:
        return ['`verdict` must be exactly "APPROVE" or "REJECT".']
    return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate review.json comments against annotated pr_diff.txt."
    )
    parser.add_argument(
        "--review-json",
        default="review.json",
        type=Path,
        help="Path to the review.json artifact to validate.",
    )
    parser.add_argument(
        "--diff",
        default="pr_diff.txt",
        type=Path,
        help="Path to the annotated PR diff consumed during review.",
    )
    args = parser.parse_args()

    payload = _load_json(args.review_json)
    try:
        diff_text = args.diff.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"review validation failed: {args.diff} does not exist", file=sys.stderr)
        return 1

    diff_line_map, diff_content_map = build_diff_maps_from_annotated_diff(diff_text)
    result = validate_review_payload(payload, diff_line_map, diff_content_map)
    errors = _validate_verdict(payload) + result.errors
    if errors:
        print("review validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        "review validation passed: "
        f"{len(result.comments)} inline comment(s), {len(diff_line_map)} diff file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
