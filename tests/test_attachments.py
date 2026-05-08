from __future__ import annotations

import base64
import unittest

from . import conftest  # noqa: F401

from oz.attachments import DEFAULT_TEXT_ATTACHMENT_MIME_TYPE, text_attachment


class TextAttachmentTest(unittest.TestCase):
    def test_text_attachment_encodes_utf8_text_for_sdk(self) -> None:
        attachment = text_attachment(
            file_name="context.txt",
            text="hello π",
        )

        self.assertEqual(attachment["file_name"], "context.txt")
        self.assertEqual(attachment["mime_type"], DEFAULT_TEXT_ATTACHMENT_MIME_TYPE)
        self.assertEqual(
            base64.b64decode(attachment["data"]).decode("utf-8"),
            "hello π",
        )

    def test_text_attachment_validates_file_name(self) -> None:
        with self.assertRaises(ValueError):
            text_attachment(file_name="  ", text="hello")

    def test_text_attachment_validates_mime_type(self) -> None:
        with self.assertRaises(ValueError):
            text_attachment(file_name="context.txt", text="hello", mime_type=" ")


if __name__ == "__main__":
    unittest.main()
