# Secrets

Nothing in this directory that ends in `.toml` other than `*.example.toml` is tracked by
git — see the repo `.gitignore`. Put credentials in `config/secrets.toml`:

```toml
[sources.web]
# Paste from a browser where you are logged into Shopee: DevTools → Network → any
# shopee.vn request → Request Headers → Cookie. It expires; re-paste when scans start
# coming back blocked.
cookie_string = "SPC_EC=…; SPC_F=…; csrftoken=…"

[sources.affiliate]
# From https://affiliate.shopee.vn → Open API. This is the sanctioned transport; prefer it.
app_id = "1234567890"
app_secret = "…"
```

## Rules this repo enforces

- **Never commit this file.** `detect-private-key` and the `.gitignore` entry are the
  backstop, not the plan.
- **Secrets are never logged.** `core/logging.py` redacts every key name above (and
  `Cookie`, `Authorization`, `token`, `api_key`, `password`, `SPC_*`, `csrftoken`, …) out of
  every record before it reaches a handler. If you add a new credential field, add its name
  to `_SECRET_KEYS` in that module in the same change.
- **`AppSettings.save()` excludes them** from the settings file it writes, so a config a
  user pastes into a bug report cannot carry a session token.
- **The app never asks for your Shopee password.** The browser source opens a real browser
  and you sign in yourself; the profile is stored locally and reused.

## Environment variables instead of a file

Every setting can come from the environment, with `__` as the nesting separator:

```bash
export SALEHUNTER_SOURCES__WEB__COOKIE_STRING="SPC_EC=…"
export SALEHUNTER_SOURCES__AFFILIATE__APP_SECRET="…"
```

Useful for a one-off live check without writing anything to disk.
