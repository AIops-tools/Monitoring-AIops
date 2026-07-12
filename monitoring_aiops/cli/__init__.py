"""CLI package for monitoring-aiops.

Re-exports ``app`` so the pyproject entry point
``monitoring-aiops = "monitoring_aiops.cli:app"`` works unchanged.
"""

from monitoring_aiops.cli._root import app

__all__ = ["app"]
