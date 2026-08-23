# Fixtures

Everything in here is **captured from the real site**, never hand-written (ADR-008).

That distinction is the whole point. A hand-written fixture pins what we *believe* Shopee's
wire format is, so the parsing tests keep passing while the real response drifts — which is
exactly the regression the offline tier exists to catch. A captured fixture pins what Shopee
actually sent.

## Capturing one

```bash
python scripts/capture_fixture.py --keyword "tai nghe" --out tests/fixtures/shopee_web/
pytest tests/sources -vv
```

The capture needs a transport that Shopee will answer: cookies in `config/secrets.toml`, or
`--source browser` with a logged-in profile. Without either you will get a 403 — which is the
adapter behaving correctly, not a bug in the script.

## Why some fixtures may be missing

`tests/sources/test_parse.py` **skips** its fixture-backed cases when the file is absent, and
covers the same parsing rules with explicit inline payloads that are labelled synthetic. So
the suite is meaningful on a fresh clone, and gets stronger the moment a real capture lands.
A committed file pretending to be a capture would be worse than an absent one.

## What is stripped before committing

`capture_fixture.py` removes per-user and per-session keys (`userid`, `tracking_info`,
`session_id`, recommendation tokens, …). Check any capture you add: these files are public.
