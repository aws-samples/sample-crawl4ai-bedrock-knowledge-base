"""Shared bootstrap for CLI scripts: path setup and logging configuration.

Allows the scripts to run directly (``python scripts/run_pipeline.py``) without a
prior ``pip install`` by adding the ``src`` directory to ``sys.path``.
"""

from __future__ import annotations

import logging
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO_ROOT, "src")

if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def configure_logging(verbose: bool = False) -> None:
    """Configure root logging for CLI use.

    Args:
        verbose: Emit DEBUG-level logs when True, otherwise INFO.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
