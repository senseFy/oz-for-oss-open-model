from __future__ import annotations

import os


BACKEND_ENV = "REVIEW_AGENT_BACKEND"
BACKEND_OZ = "oz"
BACKEND_OPEN_MODEL = "open-model"
_SUPPORTED_BACKENDS = {BACKEND_OZ, BACKEND_OPEN_MODEL}


def selected_review_backend() -> str:
    """Return the configured review-agent backend.

    The upstream Oz path stays the default. Fork deployments can opt into
    the provider-transparent backend by setting ``REVIEW_AGENT_BACKEND`` to
    ``open-model``.
    """
    raw = os.environ.get(BACKEND_ENV, BACKEND_OZ).strip().lower()
    if not raw:
        return BACKEND_OZ
    if raw not in _SUPPORTED_BACKENDS:
        raise RuntimeError(
            f"{BACKEND_ENV}={raw!r} is not supported; expected one of "
            f"{sorted(_SUPPORTED_BACKENDS)}"
        )
    return raw


def use_open_model_backend() -> bool:
    return selected_review_backend() == BACKEND_OPEN_MODEL


__all__ = [
    "BACKEND_ENV",
    "BACKEND_OPEN_MODEL",
    "BACKEND_OZ",
    "selected_review_backend",
    "use_open_model_backend",
]
