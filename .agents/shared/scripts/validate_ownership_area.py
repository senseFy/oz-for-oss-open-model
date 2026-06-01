#!/usr/bin/env python3
"""Validate review.json ``recommended_area`` against the ownership-areas list.

This script is packaged with the review-pr skill and must work when the skill
is copied into a consuming repository without the full oz-for-oss source tree.
Keep it self-contained: do not import helpers from the repository package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"ownership-area validation failed: {path} does not exist")
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"ownership-area validation failed: {path} is invalid JSON: {exc}"
        )


def _area_names(ownership_areas: Any) -> list[str]:
    if not isinstance(ownership_areas, list):
        raise SystemExit(
            "ownership-area validation failed: ownership areas must be a JSON array."
        )
    names: list[str] = []
    for entry in ownership_areas:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name)
    return names


def validate_recommended_area(review: Any, names: list[str]) -> list[str]:
    if not isinstance(review, dict):
        return ["review.json must decode to a JSON object."]
    raw_verdict = review.get("verdict")
    verdict = raw_verdict.strip().upper() if isinstance(raw_verdict, str) else ""
    if verdict not in {"APPROVE", "REJECT"}:
        return ['`verdict` must be exactly "APPROVE" or "REJECT".']

    raw_area = review.get("recommended_area")
    if verdict == "REJECT":
        if raw_area is None or (isinstance(raw_area, str) and not raw_area.strip()):
            return []
        return ['`recommended_area` must be empty or absent when `verdict` is "REJECT".']

    if not isinstance(raw_area, str) or not raw_area.strip():
        return [
            '`recommended_area` must be a non-empty string when `verdict` is "APPROVE".'
        ]
    if raw_area.strip() not in names:
        return [
            f"`recommended_area` {raw_area.strip()!r} is not one of the canonical "
            f"ownership areas: {names}."
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate review.json recommended_area against ownership_areas.json."
    )
    parser.add_argument(
        "--review-json",
        default="review.json",
        type=Path,
        help="Path to the review.json artifact to validate.",
    )
    parser.add_argument(
        "--ownership-areas",
        default="ownership_areas.json",
        type=Path,
        help="Path to the ownership_areas.json list of canonical area names.",
    )
    args = parser.parse_args()

    review = _load_json(args.review_json)
    names = _area_names(_load_json(args.ownership_areas))
    errors = validate_recommended_area(review, names)
    if errors:
        print("ownership-area validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("ownership-area validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
