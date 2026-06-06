"""Debugmaster analysis library.

Pure-stdlib core engines for the world-class debug tool. Every module degrades
gracefully: optional external tools and ML libraries are detected at runtime and
replaced by deterministic heuristics when missing, so the same code works on a
fresh CI box and on a fully-loaded workstation.
"""

__all__ = [
    "common",
    "gitrisk",
    "metrics",
    "bughunt",
    "fusion",
    "riskmodel",
    "learn",
    "hunt",
]
