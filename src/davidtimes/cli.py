"""davidtimes CLI: build | check-sources | serve."""

from __future__ import annotations

import argparse
import functools
import http.server
import logging
import sys
import warnings
from datetime import date

from dotenv import load_dotenv

from davidtimes.config import DIST_DIR, ROOT


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="davidtimes", description="A personal daily newspaper for Kindle.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="run the whole pipeline and write the edition")
    b.add_argument("--date", type=date.fromisoformat, help="edition date YYYY-MM-DD (default: today)")
    b.add_argument("--section", action="append", default=[], help="only this section id (repeatable)")
    b.add_argument("--no-llm", action="store_true", help="skip the LLM; render raw extracted text")
    b.add_argument("--offline", action="store_true", help="use cached fetches and LLM outputs only")
    b.add_argument("--force", action="store_true", help="bypass the fetch and LLM caches")
    b.add_argument("--max-pieces", type=int, help="cap pieces per section")
    b.add_argument("--minutes", type=int, help="override the reading-time target")

    sub.add_parser("check-sources", help="validate every configured source")

    s = sub.add_parser("serve", help="serve dist/ on a local static server")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--host", default="127.0.0.1")
    return p


def _serve(host: str, port: int) -> int:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST_DIR))
    with http.server.ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"Serving {DIST_DIR} at http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    warnings.filterwarnings("ignore", message="SOCKS support")  # urllib3 noise via trafilatura
    load_dotenv(ROOT / ".env")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs full request URLs at INFO, and some carry API keys in the query string.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)

    if args.command == "build":
        from davidtimes.build import BuildOptions, build

        return build(BuildOptions(
            day=args.date, sections=args.section, no_llm=args.no_llm, offline=args.offline,
            force=args.force, max_pieces=args.max_pieces, minutes=args.minutes,
        ))
    if args.command == "check-sources":
        from davidtimes.checks import check_sources

        return check_sources()
    return _serve(args.host, args.port)


if __name__ == "__main__":
    sys.exit(main())
