from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import RuntimeConfigProvider, StaticSettings


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="info-fetch-push",
        description="Fetch X posts, summarize them with DeepSeek, and push them to Feishu.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-runtime-config", help="Create a runtime config file if it does not exist.")
    subparsers.add_parser("show-config", help="Print the currently loaded runtime config.")
    subparsers.add_parser("login", help="Open a browser and save X login state locally.")
    subparsers.add_parser(
        "import-edge-session",
        help="Import X login cookies from the local Microsoft Edge profile into the Playwright session file.",
    )
    subparsers.add_parser("run-once", help="Run one fetch/summarize/push cycle.")
    subparsers.add_parser("serve", help="Run the service in a loop.")

    return parser


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    settings = StaticSettings.load()
    settings.ensure_directories()
    runtime_config_provider = RuntimeConfigProvider(
        config_path=settings.runtime_config_path,
        default_model=settings.deepseek_default_model,
    )

    if args.command == "init-runtime-config":
        created = runtime_config_provider.write_example()
        if created:
            print(f"Created runtime config at {settings.runtime_config_path}")
        else:
            print(f"Runtime config already exists at {settings.runtime_config_path}")
        return 0

    if args.command == "show-config":
        try:
            print(json.dumps(runtime_config_provider.describe(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if args.command in {"login", "import-edge-session"}:
        from .fetchers.x_scraper import XTimelineScraper

        scraper = XTimelineScraper(
            storage_state_path=settings.x_login_state_path,
            headless=False,
            browser_channel=settings.x_browser_channel,
        )

        if args.command == "login":
            scraper.login()
            print(f"Saved X login state to {settings.x_login_state_path}")
            return 0

        count = scraper.import_edge_login_state()
        print(f"Imported {count} X-related cookies into {settings.x_login_state_path}")
        return 0

    try:
        settings.validate_runtime_dependencies()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    from .pipeline import Pipeline

    pipeline = Pipeline(settings, runtime_config_provider)
    try:
        if args.command == "run-once":
            pipeline.run_once()
            return 0
        if args.command == "serve":
            pipeline.serve_forever()
            return 0
    finally:
        pipeline.close()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
