from __future__ import annotations

import argparse
import os

# Load the project-root .env into os.environ at the application entry point,
# BEFORE importing modules that read os.getenv at import time (futures_pulse,
# live_sources, …). The real shell environment still wins; the file only fills in
# what isn't already set. Kept out of the package __init__ so importing the
# library (e.g. in tests) never pulls real API keys into the process.
from .env import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402

from .api import create_app  # noqa: E402
from .database import init_db, resolve_db_path  # noqa: E402
from .seed import seed  # noqa: E402
from .service import AlphaLabService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local Alpha Lab")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--briefing-job", action="store_true", help="Generate and save a daily market research briefing, then exit")
    parser.add_argument("--sample-catalysts", action="store_true", help="Use sample catalyst fallback for the briefing job")
    args = parser.parse_args()

    # Initialize the SAME database the service/scheduler resolve to (env-pinned on
    # the server). Calling init_db() with no path would seed the bare relative
    # default and silently create a SECOND, empty DB next to the real one.
    init_db(resolve_db_path())
    if args.seed:
        seed()
    if args.briefing_job:
        saved = AlphaLabService().generate_and_save_market_briefing(live_catalysts=not args.sample_catalysts)
        print(f"saved market briefing {saved['id']} generated_at={saved['generated_at']}")
        return
    if args.host not in {"127.0.0.1", "localhost", "::1"} and os.getenv("ALPHALAB_ALLOW_PUBLIC_BIND", "").strip().lower() != "true":
        parser.error("Refusing non-loopback bind unless ALPHALAB_ALLOW_PUBLIC_BIND=true is set.")
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
