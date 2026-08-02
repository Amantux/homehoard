"""Startup configuration validator: ``python3 -m app.config_check``.

The entrypoint runs this BEFORE anything else starts, so a misconfigured
deployment fails immediately with every problem listed at once, instead of
booting into a confusing 500 on some later request.

It also prints which settings are non-default **and where each came from**,
which is the single most useful thing to ask an operator for when diagnosing
"but I set that option". Secrets are always redacted, and the database is
described by scheme only — never as a DSN, which embeds a password.

Exit codes:
  0  configuration is valid (warnings may still have been printed)
  1  configuration is invalid; the app would refuse to start
  2  the checker itself failed — a checker that crashes silently is useless
"""
from __future__ import annotations

import argparse
import json
import sys

from .settings import ConfigError, load_settings


def _describe_db(settings) -> str:
    """Human-readable database target that never leaks credentials."""
    uri = settings.sqlalchemy_uri
    if uri.startswith("sqlite"):
        return f"sqlite ({uri[len('sqlite:///'):]})"
    return f"{uri.split('://', 1)[0]} (connection details hidden)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="config_check", description=__doc__)
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    parser.add_argument("--ha-options", default="/data/options.json",
                        help="path to the Home Assistant add-on options file")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(ha_options_path=args.ha_options)
    except ConfigError as exc:
        if args.json:
            print(json.dumps({"ok": False, "errors": exc.errors}, indent=2))
        else:
            print("HomeHoard configuration is INVALID:", file=sys.stderr)
            for err in exc.errors:
                print(f"  - {err}", file=sys.stderr)
            print("\nThe add-on will not start until these are fixed.", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - a checker that crashes is useless
        print(f"config_check failed unexpectedly: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "ok": True,
            "settings": settings.redacted(),
            "sources": settings.sources,
            "database": _describe_db(settings),
            "warnings": list(settings.warnings),
        }, indent=2, sort_keys=True))
        return 0

    print("HomeHoard configuration is valid.")
    print(f"  data dir : {settings.data_dir}")
    print(f"  database : {_describe_db(settings)}")
    print(f"  auth     : {'DISABLED' if settings.DISABLE_AUTH else 'enabled'}")
    print(f"  MCP      : {'on' if settings.MCP_ENABLED else 'off'}"
          f"{' (exposed externally)' if settings.MCP_EXPOSE_EXTERNAL else ''}")
    print(f"  AI       : {settings.AI_PROVIDER or 'off'}")

    redacted = settings.redacted()
    non_default = [(name, src) for name, src in sorted(settings.sources.items())
                   if src != "default"]
    if non_default:
        print("\nNon-default settings (and where each came from):")
        for name, src in non_default:
            print(f"  {name} = {redacted[name]!r}  [{src}]")

    if settings.warnings:
        print("\nWarnings:")
        for warning in settings.warnings:
            print(f"  ! {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
