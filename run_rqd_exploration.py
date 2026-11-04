"""Root entry point for the RQD exploration pilot."""

import sys

from src.rqd_exploration.cli import main


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "raw-rqd":
        from src.rqd_exploration.raw_rqd_search import main as raw_rqd_main

        raise SystemExit(raw_rqd_main(sys.argv[2:]))
    raise SystemExit(main())
