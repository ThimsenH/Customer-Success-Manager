"""Command line: python -m csm [generate|analyse|build|reset-journal]"""

import sys

from . import generate, journal, pipeline
from .db import DB_PATH, connect


def main(argv):
    command = argv[1] if len(argv) > 1 else "build"
    if command in ("generate", "build"):
        generate.build().close()
        print(f"Generated synthetic portfolio in {DB_PATH}")
    if command in ("analyse", "build"):
        conn = connect()
        n_health, n_signals = pipeline.analyse(conn)
        conn.close()
        print(f"Computed {n_health} health scores and {n_signals} signals")
    if command == "reset-journal":
        journal.reset().close()
        print(f"Journal reset to demo history in {journal.JOURNAL_PATH}")
    if command not in ("generate", "analyse", "build", "reset-journal"):
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
