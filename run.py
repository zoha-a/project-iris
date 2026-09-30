#!/usr/bin/env python3
"""Zero-install entry point so a clean checkout runs with one command.

    python run.py demo

Installing the package (``pip install -e .``) gives the same CLI as
``iris-ingest`` or ``python -m iris_ingest``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from iris_ingest.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
