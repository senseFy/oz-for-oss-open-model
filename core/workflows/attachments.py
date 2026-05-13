from __future__ import annotations

from typing import Any, Iterable, Mapping

from oz.attachments import SdkAttachment as Attachment


def payload_without_fields(
    context: Mapping[str, Any],
    fields: Iterable[str],
) -> dict[str, Any]:
    excluded = set(fields)
    return {key: value for key, value in dict(context).items() if key not in excluded}
