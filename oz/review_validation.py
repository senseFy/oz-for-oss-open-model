from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, TypedDict


class ReviewComment(TypedDict, total=False):
    """Normalized review comment accepted by ``PullRequest.create_review``."""

    path: str
    line: int
    side: str
    body: str
    start_line: int
    start_side: str


@dataclass(frozen=True)
class ReviewValidationResult:
    """Validated ``review.json`` fields plus any dropped-comment errors."""

    summary: str
    comments: list[ReviewComment]
    errors: list[str]

    @property
    def is_valid(self) -> bool:
        return not self.errors


HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)

SUGGESTION_BLOCK_PATTERN = re.compile(
    r"```suggestion[^\n]*\r?\n(?P<content>.*?)\r?\n```",
    re.DOTALL,
)

ANNOTATED_OLD_PATTERN = re.compile(r"^\[OLD:(?P<old>\d+)\] ?(?P<text>.*)$")
ANNOTATED_NEW_PATTERN = re.compile(r"^\[NEW:(?P<new>\d+)\] ?(?P<text>.*)$")
ANNOTATED_CONTEXT_PATTERN = re.compile(
    r"^\[OLD:(?P<old>\d+),NEW:(?P<new>\d+)\] ?(?P<text>.*)$"
)


def normalize_review_path(value: Any) -> str:
    path = str(value or "").strip()
    path = re.sub(r"^(a/|b/|\./)", "", path)
    return path


def commentable_lines_for_patch(patch: str | None) -> dict[str, set[int]]:
    commentable_lines = {"LEFT": set(), "RIGHT": set()}
    if not patch:
        return commentable_lines

    old_line: int | None = None
    new_line: int | None = None

    for raw_line in patch.splitlines():
        header_match = HUNK_HEADER_PATTERN.match(raw_line)
        if header_match:
            old_line = int(header_match.group("old_start"))
            new_line = int(header_match.group("new_start"))
            continue
        if old_line is None or new_line is None or raw_line.startswith("\\"):
            continue
        marker = raw_line[:1]
        if marker == "-":
            commentable_lines["LEFT"].add(old_line)
            old_line += 1
        elif marker == "+":
            commentable_lines["RIGHT"].add(new_line)
            new_line += 1
        elif marker == " ":
            commentable_lines["LEFT"].add(old_line)
            commentable_lines["RIGHT"].add(new_line)
            old_line += 1
            new_line += 1

    return commentable_lines


def line_content_for_patch(patch: str | None) -> dict[str, dict[int, str]]:
    """Return file content known from a unified patch, keyed by side and line."""
    line_content: dict[str, dict[int, str]] = {"LEFT": {}, "RIGHT": {}}
    if not patch:
        return line_content

    old_line: int | None = None
    new_line: int | None = None

    for raw_line in patch.splitlines():
        header_match = HUNK_HEADER_PATTERN.match(raw_line)
        if header_match:
            old_line = int(header_match.group("old_start"))
            new_line = int(header_match.group("new_start"))
            continue
        if old_line is None or new_line is None or raw_line.startswith("\\"):
            continue
        marker = raw_line[:1]
        text = raw_line[1:]
        if marker == "-":
            line_content["LEFT"][old_line] = text
            old_line += 1
        elif marker == "+":
            line_content["RIGHT"][new_line] = text
            new_line += 1
        elif marker == " ":
            line_content["LEFT"][old_line] = text
            line_content["RIGHT"][new_line] = text
            old_line += 1
            new_line += 1

    return line_content


def build_diff_maps_from_files(
    files: list[Any],
) -> tuple[dict[str, dict[str, set[int]]], dict[str, dict[str, dict[int, str]]]]:
    diff_line_map: dict[str, dict[str, set[int]]] = {}
    diff_content_map: dict[str, dict[str, dict[int, str]]] = {}
    for file in files:
        path = normalize_review_path(file.filename)
        patch = file.patch
        diff_line_map[path] = commentable_lines_for_patch(patch)
        diff_content_map[path] = line_content_for_patch(patch)
    return diff_line_map, diff_content_map


def serialize_diff_line_map(
    diff_line_map: dict[str, dict[str, set[int]]],
) -> dict[str, dict[str, list[int]]]:
    return {
        path: {side: sorted(lines) for side, lines in sides.items()}
        for path, sides in diff_line_map.items()
    }


def deserialize_diff_line_map(
    serialized: Mapping[str, Mapping[str, list[int]]],
) -> dict[str, dict[str, set[int]]]:
    return {
        str(path): {str(side): set(lines or []) for side, lines in sides.items()}
        for path, sides in serialized.items()
    }


def serialize_diff_content_map(
    diff_content_map: dict[str, dict[str, dict[int, str]]],
) -> dict[str, dict[str, dict[str, str]]]:
    return {
        path: {
            side: {str(line): text for line, text in lines.items()}
            for side, lines in sides.items()
        }
        for path, sides in diff_content_map.items()
    }


def deserialize_diff_content_map(
    serialized: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> dict[str, dict[str, dict[int, str]]]:
    return {
        str(path): {
            str(side): {int(line): str(text) for line, text in lines.items()}
            for side, lines in sides.items()
        }
        for path, sides in serialized.items()
    }


def build_diff_maps_from_annotated_diff(
    diff_text: str,
) -> tuple[dict[str, dict[str, set[int]]], dict[str, dict[str, dict[int, str]]]]:
    """Build validation maps from the annotated diff shown to review agents."""
    diff_line_map: dict[str, dict[str, set[int]]] = {}
    diff_content_map: dict[str, dict[str, dict[int, str]]] = {}
    current_path = ""
    old_path = ""

    def ensure_path(path: str) -> None:
        diff_line_map.setdefault(path, {"LEFT": set(), "RIGHT": set()})
        diff_content_map.setdefault(path, {"LEFT": {}, "RIGHT": {}})

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_path = ""
            old_path = ""
            continue
        if raw_line.startswith("--- "):
            candidate = raw_line[4:].strip()
            old_path = (
                "" if candidate == "/dev/null" else normalize_review_path(candidate)
            )
            continue
        if raw_line.startswith("+++ "):
            candidate = raw_line[4:].strip()
            if candidate == "/dev/null":
                current_path = old_path
            else:
                current_path = normalize_review_path(candidate)
            if not current_path:
                continue
            ensure_path(current_path)
            continue
        if not current_path:
            continue
        old_match = ANNOTATED_OLD_PATTERN.match(raw_line)
        if old_match:
            line = int(old_match.group("old"))
            text = old_match.group("text")
            diff_line_map[current_path]["LEFT"].add(line)
            diff_content_map[current_path]["LEFT"][line] = text
            continue
        new_match = ANNOTATED_NEW_PATTERN.match(raw_line)
        if new_match:
            line = int(new_match.group("new"))
            text = new_match.group("text")
            diff_line_map[current_path]["RIGHT"].add(line)
            diff_content_map[current_path]["RIGHT"][line] = text
            continue
        context_match = ANNOTATED_CONTEXT_PATTERN.match(raw_line)
        if context_match:
            old_line = int(context_match.group("old"))
            new_line = int(context_match.group("new"))
            text = context_match.group("text")
            diff_line_map[current_path]["LEFT"].add(old_line)
            diff_line_map[current_path]["RIGHT"].add(new_line)
            diff_content_map[current_path]["LEFT"][old_line] = text
            diff_content_map[current_path]["RIGHT"][new_line] = text

    return diff_line_map, diff_content_map


def _extract_suggestion_blocks(body: str | None) -> list[list[str]]:
    """Extract the line content of each ```suggestion fenced block."""
    blocks: list[list[str]] = []
    for match in SUGGESTION_BLOCK_PATTERN.finditer(body or ""):
        content = match.group("content")
        lines = [line.rstrip("\r") for line in content.split("\n")]
        blocks.append(lines)
    return blocks


def _validate_suggestion_blocks(
    comment: dict[str, Any],
    diff_content_map: dict[str, dict[str, dict[int, str]]],
) -> list[str]:
    """Return validation errors for suggestion blocks in a comment."""
    errors: list[str] = []
    body = comment.get("body") or ""
    blocks = _extract_suggestion_blocks(body)
    if not blocks:
        return errors

    path = comment.get("path") or ""
    side = comment.get("side") or "RIGHT"
    line_no = comment.get("line")
    if not isinstance(line_no, int):
        return errors
    start_line = comment.get("start_line") or line_no
    content_for_side = diff_content_map.get(path, {}).get(side, {})

    for block_index, block_lines in enumerate(blocks):
        if not block_lines or block_lines == [""]:
            continue
        prev_context = content_for_side.get(start_line - 1)
        next_context = content_for_side.get(line_no + 1)
        first_line = block_lines[0]
        last_line = block_lines[-1]
        if prev_context is not None and first_line == prev_context:
            errors.append(
                f"suggestion block {block_index} duplicates the context line immediately above "
                f"`start_line` ({start_line - 1}); that line is not replaced and will appear twice after the suggestion is applied"
            )
        if next_context is not None and last_line == next_context:
            errors.append(
                f"suggestion block {block_index} duplicates the context line immediately below "
                f"`line` ({line_no + 1}); that line is not replaced and will appear twice after the suggestion is applied"
            )
    return errors


def validate_review_payload(
    review: Any,
    diff_line_map: dict[str, dict[str, set[int]]],
    diff_content_map: dict[str, dict[str, dict[int, str]]] | None = None,
) -> ReviewValidationResult:
    """Validate and normalize a ``review.json`` payload against a PR diff."""
    if not isinstance(review, dict):
        raise ValueError("Review payload must be a JSON object.")

    summary = review.get("summary") or ""
    if not isinstance(summary, str):
        raise ValueError("Review payload `summary` must be a string.")

    raw_comments = review.get("comments") or []
    if not isinstance(raw_comments, list):
        raise ValueError("Review payload `comments` must be a list.")

    normalized_comments: list[ReviewComment] = []
    errors: list[str] = []

    for index, raw_comment in enumerate(raw_comments):
        if not isinstance(raw_comment, dict):
            errors.append(f"`comments[{index}]` must be an object.")
            continue

        path = normalize_review_path(raw_comment.get("path"))
        line = raw_comment.get("line")
        body = str(raw_comment.get("body") or "").strip()
        side = (
            raw_comment.get("side")
            if raw_comment.get("side") in {"LEFT", "RIGHT"}
            else "RIGHT"
        )

        if not path:
            errors.append(f"`comments[{index}]` is missing `path`.")
            continue
        if path not in diff_line_map:
            errors.append(
                f"`comments[{index}]` references `{path}`, which is not part of the PR diff. Move that feedback to `summary` instead."
            )
            continue
        if not isinstance(line, int) or line <= 0:
            errors.append(
                f"`comments[{index}]` for `{path}` must include a positive integer `line`."
            )
            continue
        if not body:
            errors.append(f"`comments[{index}]` for `{path}` is missing `body`.")
            continue

        allowed_lines = diff_line_map[path][side]
        if line not in allowed_lines:
            errors.append(
                f"`comments[{index}]` references `{path}:{line}` on `{side}`, which is not commentable in the PR diff."
            )
            continue

        normalized_comment: ReviewComment = {
            "path": path,
            "line": line,
            "side": side,
            "body": body,
        }

        if "start_line" in raw_comment and raw_comment.get("start_line") is not None:
            start_line = raw_comment.get("start_line")
            if not isinstance(start_line, int) or start_line <= 0 or start_line >= line:
                errors.append(
                    f"`comments[{index}]` for `{path}` has invalid `start_line`; it must be a positive integer smaller than `line`."
                )
                continue
            if start_line not in allowed_lines:
                errors.append(
                    f"`comments[{index}]` references `{path}:{start_line}` on `{side}` as `start_line`, which is not commentable in the PR diff."
                )
                continue
            normalized_comment["start_line"] = start_line
            normalized_comment["start_side"] = side

        if diff_content_map is not None:
            suggestion_errors = _validate_suggestion_blocks(
                normalized_comment, diff_content_map
            )
            if suggestion_errors:
                for err in suggestion_errors:
                    errors.append(
                        f"`comments[{index}]` for `{path}:{line}` on `{side}` has an invalid suggestion block: {err}."
                    )
                continue

        normalized_comments.append(normalized_comment)

    return ReviewValidationResult(
        summary=summary.strip(),
        comments=normalized_comments,
        errors=errors,
    )


def normalize_review_payload(
    review: Any,
    diff_line_map: dict[str, dict[str, set[int]]],
    diff_content_map: dict[str, dict[str, dict[int, str]]] | None = None,
) -> tuple[str, list[ReviewComment]]:
    """Compatibility wrapper that logs and drops invalid inline comments."""
    result = validate_review_payload(review, diff_line_map, diff_content_map)
    for err in result.errors:
        print(f"[review-validation] Dropped comment: {err}")
    return result.summary, result.comments
