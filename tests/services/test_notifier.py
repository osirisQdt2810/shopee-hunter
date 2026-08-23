"""The notifier's shell escaping.

Both platform paths build a command string containing a *product name*, which comes off
Shopee and is entirely attacker-controlled. Escaping is the only thing between a listing
titled `"; rm -rf ~; echo "` and that command running on the user's machine, so it gets a
test even though the surrounding notification code needs a real desktop.
"""

from __future__ import annotations

import pytest

from shopee_hunter.services.notifier import _escape_applescript, _escape_powershell


class TestAppleScriptEscaping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('Tai nghe "Pro"', 'Tai nghe \\"Pro\\"'),
            ("back\\slash", "back\\\\slash"),
            # Backslash first, then quote: escaping in the other order would double-escape
            # the backslash this inserts and leave the quote live.
            ('a\\"b', 'a\\\\\\"b'),
        ],
    )
    def test_quotes_and_backslashes_are_neutralised(
        self, raw: str, expected: str
    ) -> None:
        assert _escape_applescript(raw) == expected

    def test_a_closing_quote_cannot_escape_the_string(self) -> None:
        hostile = '"; do shell script "rm -rf ~'

        escaped = _escape_applescript(hostile)

        assert '"' not in escaped.replace('\\"', "")

    def test_ordinary_vietnamese_text_is_untouched(self) -> None:
        assert _escape_applescript("Tai nghe Bluetooth chống ồn") == (
            "Tai nghe Bluetooth chống ồn"
        )


class TestPowerShellEscaping:
    def test_single_quotes_are_doubled(self) -> None:
        assert _escape_powershell("it's a deal") == "it''s a deal"

    def test_a_closing_quote_cannot_escape_the_string(self) -> None:
        hostile = "'; Remove-Item -Recurse ~; '"

        escaped = _escape_powershell(hostile)

        # Every quote is doubled, so none of them can terminate the literal.
        assert escaped.count("'") == hostile.count("'") * 2

    def test_ordinary_text_is_untouched(self) -> None:
        assert _escape_powershell("Tai nghe Bluetooth") == "Tai nghe Bluetooth"
