"""Shared registry of skills resolved from the common-skills repository.

The membership set is maintained statically here for now; the intended
end-state is not to hardcode these names.
"""

from __future__ import annotations

COMMON_SKILL_NAMES = frozenset(
    {
        "check-impl-against-spec",
        "implement-specs",
        "review-pr",
        "spec-driven-implementation",
        "write-product-spec",
        "write-tech-spec",
    }
)
