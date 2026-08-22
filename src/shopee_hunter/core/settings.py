"""The settings tree: one Pydantic model, three sources, one precedence order.

Precedence (lowest to highest): model defaults → ``config/settings.toml`` (shipped) →
the user's own ``settings.toml`` in the OS config dir → ``SALEHUNTER_*`` environment
variables. Env wins so a live debugging session can flip a source without editing a file
the app also writes.

Two base classes with different strictness, on purpose:

* :class:`PersistedModel` tolerates unknown keys — a settings file written by a *newer*
  build must not make an older one refuse to start. That failure mode is invisible in
  development and total in the field.
* :class:`StrictModel` rejects them — used for wire payloads, where an unexpected key means
  we are parsing something we do not understand and should say so.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal, Optional

from platformdirs import PlatformDirs
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import ConfigError
from .logging import get_logger

APP_NAME = "SaleHunter"
APP_AUTHOR = "osirisQdt2810"
ENV_PREFIX = "SALEHUNTER_"

_dirs = PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR, roaming=True)


class AppPaths:
    """Where the app is allowed to write, per OS.

    Never construct these by hand: ``~/Library/...`` on macOS and ``%APPDATA%`` on Windows
    are not interchangeable, and a hard-coded one is a cross-platform bug that only shows
    up on the machine you do not have.
    """

    config_dir = Path(_dirs.user_config_dir)
    data_dir = Path(_dirs.user_data_dir)
    cache_dir = Path(_dirs.user_cache_dir)
    log_dir = Path(_dirs.user_log_dir)

    @classmethod
    def settings_file(cls) -> Path:
        return cls.config_dir / "settings.toml"

    @classmethod
    def secrets_file(cls) -> Path:
        return cls.config_dir / "secrets.toml"

    @classmethod
    def database_file(cls) -> Path:
        return cls.data_dir / "sale_hunter.sqlite3"

    @classmethod
    def browser_profile_dir(cls) -> Path:
        return cls.data_dir / "browser-profile"

    @classmethod
    def log_file(cls) -> Path:
        return cls.log_dir / "sale_hunter.log"

    @classmethod
    def ensure(cls) -> None:
        """Create every directory the app writes to. Safe to call repeatedly."""
        for directory in (cls.config_dir, cls.data_dir, cls.cache_dir, cls.log_dir):
            directory.mkdir(parents=True, exist_ok=True)


class StrictModel(BaseModel):
    """Base for never-persisted payloads: unknown keys are an error worth hearing about."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PersistedModel(BaseModel):
    """Base for anything read back from disk: unknown keys are ignored, not fatal."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class StorefrontSettings(PersistedModel):
    """Which Shopee storefront to hunt on. Domain and currency must agree."""

    domain: str = "shopee.vn"
    currency: str = "VND"
    language: str = "vi"

    @field_validator("domain")
    @classmethod
    def _plausible_domain(cls, value: str) -> str:
        value = (
            value.strip()
            .lower()
            .removeprefix("https://")
            .removeprefix("http://")
            .strip("/")
        )
        if not value.startswith("shopee."):
            raise ValueError("domain must be a Shopee storefront, e.g. shopee.vn")
        return value


class WebSourceSettings(PersistedModel):
    """The plain-HTTP adapter. Works only with cookies from a real browser session."""

    enabled: bool = True
    cookie_string: str = Field(default="", repr=False)
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    timeout_seconds: float = 20.0
    # Shopee answers a bot-flagged request with HTTP 200 + `error: 10`, so retries must be
    # few and slow; hammering it converts a soft block into a hard one.
    max_retries: int = 2
    retry_backoff_seconds: float = 5.0


class BrowserSourceSettings(PersistedModel):
    """The Playwright adapter: the user's own logged-in profile drives the requests."""

    enabled: bool = False
    channel: Literal["chromium", "chrome", "msedge"] = "chrome"
    headless: bool = False
    profile_dir: Optional[Path] = None
    nav_timeout_seconds: float = 45.0


class AffiliateSourceSettings(PersistedModel):
    """The official signed Open/Affiliate API — the only sanctioned transport."""

    enabled: bool = False
    app_id: str = ""
    app_secret: str = Field(default="", repr=False)
    endpoint: str = "https://open-api.affiliate.shopee.vn/graphql"


class SourcesSettings(PersistedModel):
    """Adapter selection. ``order`` is the fallback chain, tried left to right."""

    order: list[str] = Field(default_factory=lambda: ["affiliate", "browser", "web"])
    web: WebSourceSettings = Field(default_factory=WebSourceSettings)
    browser: BrowserSourceSettings = Field(default_factory=BrowserSourceSettings)
    affiliate: AffiliateSourceSettings = Field(default_factory=AffiliateSourceSettings)

    @field_validator("order")
    @classmethod
    def _known_sources(cls, value: list[str]) -> list[str]:
        allowed = {"affiliate", "browser", "web", "fixture"}
        unknown = [name for name in value if name not in allowed]
        if unknown:
            raise ValueError(
                f"unknown source(s): {', '.join(unknown)}; allowed: {sorted(allowed)}"
            )
        if not value:
            raise ValueError("at least one source must be configured")
        return value


class RateLimitSettings(PersistedModel):
    """Hard ceiling on outbound requests. Raising these is the user's own risk."""

    requests_per_second: float = 0.5
    burst: int = 4
    max_concurrent: int = 2

    @field_validator("requests_per_second")
    @classmethod
    def _sane_rate(cls, value: float) -> float:
        if not 0.01 <= value <= 5.0:
            raise ValueError("requests_per_second must be between 0.01 and 5.0")
        return value


class ScanSettings(PersistedModel):
    """How a scan behaves. Defaults are tuned for "a watcher", not "a crawler"."""

    items_per_watch: int = 60
    min_discount_pct: float = 20.0

    @field_validator("items_per_watch")
    @classmethod
    def _bounded_page_span(cls, value: int) -> int:
        """Cap the pages one watch may request — by clamping, never by refusing.

        `SearchQuery.page_count` is derived from this and each page is a separate request.
        The limiter charges per request so a large value can no longer burst past the bucket
        (ADR-007); it can still make one watch monopolise the budget while the others wait.
        300 is five pages, already more than a person reads.

        Clamped rather than rejected because this value is *persisted*. ADR-009's whole point
        is that a settings file must never stop the app starting — `AppSettings.load` turns
        any validation error into a fatal `ConfigError`, so raising here would mean a file
        written by a build that allowed 600 bricks the launch of a build that does not. A
        ceiling that silently costs you the tail of one search is a far better failure than
        an app that will not open.
        """
        clamped = max(1, min(value, 300))
        if clamped != value:
            get_logger("settings").warning(
                "scan.items_per_watch %d is outside 1..300; using %d", value, clamped
            )
        return clamped

    genuine_only: bool = True
    history_lookback_days: int = 90
    auto_scan: bool = True
    # None = derive from the sale calendar (the point of having one).
    interval_override_seconds: Optional[int] = None
    notify_on_new_deal: bool = True
    notify_min_score: float = 60.0


class UiSettings(PersistedModel):
    """Look and feel. Every value here is consumed by the QML Theme singleton."""

    theme: Literal["dark", "light", "system"] = "dark"
    accent: str = "#FF5722"
    translucent_window: bool = True
    blur_strength: float = 0.85
    reduced_motion: bool = False
    animation_scale: float = 1.0
    window_width: int = 1280
    window_height: int = 820

    @field_validator("accent")
    @classmethod
    def _hex_colour(cls, value: str) -> str:
        value = value.strip()
        if not (len(value) == 7 and value.startswith("#")):
            raise ValueError("accent must be a #rrggbb hex colour")
        int(value[1:], 16)
        return value.upper()


class AppSettings(PersistedModel):
    """Root of the settings tree."""

    storefront: StorefrontSettings = Field(default_factory=StorefrontSettings)
    sources: SourcesSettings = Field(default_factory=SourcesSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    scan: ScanSettings = Field(default_factory=ScanSettings)
    ui: UiSettings = Field(default_factory=UiSettings)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    demo_mode: bool = False

    # -- loading ----------------------------------------------------------------
    @classmethod
    def load(
        cls,
        *,
        bundled: Optional[Path] = None,
        user: Optional[Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> AppSettings:
        """Build settings from every layer, lowest precedence first.

        Args:
            bundled: The repo's ``config/settings.toml`` (optional; ships defaults).
            user: The user's own file (optional; written by the Settings view).
            env: Environment mapping; defaults to ``os.environ``.

        Raises:
            ConfigError: A layer is unreadable, malformed, or contradicts a validator.
        """
        merged: dict[str, Any] = {}
        for path in (bundled, user):
            if path is not None and path.is_file():
                _deep_update(merged, _read_toml(path))
        _deep_update(merged, _env_overrides(os.environ if env is None else env))
        try:
            return cls.model_validate(merged)
        except Exception as exc:  # pydantic ValidationError and friends
            raise ConfigError(f"invalid settings: {exc}") from exc

    def save(self, path: Optional[Path] = None) -> Path:
        """Write the tree back as TOML, secrets excluded.

        Credentials live in ``secrets.toml`` / the keyring; writing them into the settings
        file the user might paste into a bug report is how tokens leak.
        """
        target = path or AppPaths.settings_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="json", exclude=_SECRET_FIELDS)
        target.write_text(_to_toml(payload), encoding="utf-8")
        return target


# Fields never written to the settings file (see AppSettings.save).
_SECRET_FIELDS: dict[str, Any] = {
    "sources": {
        "web": {"cookie_string"},
        "affiliate": {"app_secret"},
    }
}


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read settings from {path}: {exc}") from exc


def _deep_update(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge — a partial user file must not blank a whole section."""
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _coerce(raw: str) -> Any:
    """Best-effort scalar parse for an env value (bool → int → float → csv → str)."""
    lowered = raw.strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    for caster in (int, float):
        try:
            return caster(raw)
        except ValueError:
            continue
    if "," in raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


def _env_overrides(env: dict[str, str]) -> dict[str, Any]:
    """``SALEHUNTER_UI__ACCENT=#00E5FF`` → ``{"ui": {"accent": "#00E5FF"}}``.

    Double underscore is the nesting separator (single underscores appear inside real field
    names like ``min_discount_pct``, so they cannot be it).
    """
    out: dict[str, Any] = {}
    for key, value in env.items():
        if not key.startswith(ENV_PREFIX) or not value:
            continue
        path = key[len(ENV_PREFIX) :].lower().split("__")
        cursor = out
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = _coerce(value)
    return out


def _to_toml(payload: dict[str, Any], _prefix: str = "") -> str:
    """Minimal TOML writer — avoids a dependency for the one thing we write.

    Handles exactly the shapes this settings tree produces: nested tables, strings, bools,
    numbers, ``None`` (omitted), and flat lists of scalars.
    """
    scalars: list[str] = []
    tables: list[str] = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, dict):
            name = f"{_prefix}.{key}" if _prefix else key
            tables.append(f"\n[{name}]\n{_to_toml(value, name)}")
        elif isinstance(value, bool):
            scalars.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, (int, float)):
            scalars.append(f"{key} = {value}")
        elif isinstance(value, (list, tuple)):
            rendered = ", ".join(f'"{item}"' for item in value)
            scalars.append(f"{key} = [{rendered}]")
        else:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            scalars.append(f'{key} = "{escaped}"')
    return "\n".join(scalars) + ("\n" if scalars else "") + "".join(tables)
