"""rs_backend.py -- Fastest available Reed-Solomon backend for the tape decoder.

Exports:
  RSCodec          -- fastest available RSCodec class (creedsolo if built, else reedsolo)
  ReedSolomonError -- corresponding error class from the same module
  BACKEND          -- "creedsolo" or "reedsolo" (for diagnostics/logging)

Usage:
    from rs_backend import RSCodec, ReedSolomonError, BACKEND

The API of RSCodec is identical between the two backends (same reedsolo project).
The fallback to pure-Python reedsolo is silent and produces byte-identical results.

creedsolo is the Cython-compiled extension shipped alongside reedsolo.  It is NOT
on PyPI as a standalone package; it must be compiled from the reedsolo source with
Cython+clang and installed manually (see experiments/tape_v2/README_rs_backend.md
for the build recipe, or issue #21).

Uncorrectable codewords: both backends raise a ReedSolomonError (distinct classes,
both subclass Exception).  The existing decoder catch clauses use
  except (ReedSolomonError, Exception):
which catches both, so no decoder logic changes are needed for exception handling.
The ReedSolomonError exported here always matches the active backend.
"""
from __future__ import annotations

try:
    from creedsolo import RSCodec, ReedSolomonError  # type: ignore[import]
    BACKEND: str = "creedsolo"
except ImportError:
    from reedsolo import RSCodec, ReedSolomonError   # type: ignore[import]
    BACKEND = "reedsolo"

__all__ = ["RSCodec", "ReedSolomonError", "BACKEND"]
