"""Secret redaction — the one security primitive in this app.

A Shopee session cookie is the user's whole account. The app never asks for a password, so
the cookie *is* the credential, and the realistic way it escapes is not a breach but a log
line pasted into a bug report. That makes `redact` load-bearing, and it had no test at all.
"""

from __future__ import annotations

import logging

import pytest

from shopee_hunter.core.logging import RedactingFilter, redact


class TestRedact:
    @pytest.mark.parametrize(
        "text",
        [
            "cookie=SPC_EC=abc123",
            "Cookie: SPC_EC=abc123",
            'authorization: "SHA256 Credential=x, Signature=deadbeef"',
            "csrftoken=tok123",
            "token=xyz789",
            "api_key=k-123",
            "password=hunter2",
        ],
    )
    def test_a_credential_never_survives(self, text: str) -> None:
        assert "<redacted>" in redact(text)

    @pytest.mark.parametrize(
        ("text", "leaked"),
        [
            # The two settings field names. `\bsecret\b` cannot match inside `app_secret`
            # because `_` is a word character, so the generic stem missed the exact spelling
            # these values carry in a settings dump — the most likely way either reaches a
            # log at all.
            ("app_secret=sup3rs3cret", "sup3rs3cret"),
            ("cookie_string=SPC_EC=abc123; csrftoken=t", "abc123"),
        ],
    )
    def test_the_settings_field_names_are_covered(self, text: str, leaked: str) -> None:
        assert leaked not in redact(text)

    def test_ordinary_text_is_left_alone(self) -> None:
        """Over-redaction makes logs useless, which gets redaction switched off."""
        message = "search 'tai nghe bluetooth' returned 42 items in 1.3s"

        assert redact(message) == message


class TestRedactingFilter:
    def _record(self, msg: str, *args: object) -> logging.LogRecord:
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=args,
            exc_info=None,
        )

    def test_the_message_is_redacted(self) -> None:
        record = self._record("sending cookie=SPC_EC=abc123")

        RedactingFilter().filter(record)

        assert "abc123" not in record.getMessage()

    def test_a_secret_in_an_argument_is_redacted(self) -> None:
        record = self._record("sending %s", "cookie=SPC_EC=abc123")

        RedactingFilter().filter(record)

        assert "abc123" not in record.getMessage()

    def test_a_non_string_argument_keeps_its_type(self) -> None:
        """The regression that made a log line about a failure fail.

        An earlier version coerced every argument with `str()`, so a float bound for `%.0f`
        arrived as `"120.0"` and formatting raised a TypeError — while reporting a blocked
        request. Found by the first live run.
        """
        record = self._record("backing off %.0fs after %d block(s)", 120.0, 1)

        RedactingFilter().filter(record)

        assert record.getMessage() == "backing off 120s after 1 block(s)"

    @pytest.mark.parametrize(
        "mapping",
        [
            {"Authorization": "SHA256 Credential=x, Signature=deadbeef"},
            {"cookie_string": "SPC_EC=abc123"},
            {"app_secret": "hunter2"},
            {"csrftoken": "tok123"},
        ],
    )
    def test_a_python_mapping_repr_is_covered(self, mapping: dict) -> None:
        """`logger.debug("headers=%s", headers)` is the obvious way a header dict is logged.

        A dict repr uses single quotes and a colon, so it matched neither the JSON pattern
        (double quotes) nor the query-string pattern (`=`). No call site logs a mapping
        today, which is exactly why the gap would go unnoticed the day one does.
        """
        redacted = redact(str(mapping))

        for secret in mapping.values():
            assert secret not in redacted
        assert "<redacted>" in redacted
