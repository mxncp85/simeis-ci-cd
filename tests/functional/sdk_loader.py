from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDK_PATH = ROOT / "sdk" / "python.py"

_SPEC = spec_from_file_location("simeis_functional_sdk", SDK_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load SDK module from {SDK_PATH}")

_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

SimeisSDK = _MODULE.SimeisSDK
SimeisError = _MODULE.SimeisError
