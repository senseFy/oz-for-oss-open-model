from __future__ import annotations

import base64
from typing import TypedDict


DEFAULT_TEXT_ATTACHMENT_MIME_TYPE = "text/plain"


class SdkAttachment(TypedDict):
    """SDK-compatible attachment payload for ``client.agent.run``."""
    data: str
    file_name: str
    mime_type: str


def text_attachment(
    file_name: str,
    text: str,
    *,
    mime_type: str = DEFAULT_TEXT_ATTACHMENT_MIME_TYPE,
) -> SdkAttachment:
    """Return a base64-encoded text attachment for an Oz SDK run."""
    if not isinstance(text, str):
        raise TypeError("Attachment text must be a string")
    normalized_file_name = file_name.strip()
    if not normalized_file_name:
        raise ValueError("Attachment file_name must be a non-empty string")
    normalized_mime_type = mime_type.strip()
    if not normalized_mime_type:
        raise ValueError("Attachment mime_type must be a non-empty string")
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return {
        "data": encoded,
        "file_name": normalized_file_name,
        "mime_type": normalized_mime_type,
    }


__all__ = [
    "DEFAULT_TEXT_ATTACHMENT_MIME_TYPE",
    "SdkAttachment",
    "text_attachment",
]
