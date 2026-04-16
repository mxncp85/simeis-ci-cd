from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SDK_PATH = Path(__file__).resolve().parents[2] / "sdk" / "python.py"
_SDK_SPEC = spec_from_file_location("simeis_shared_sdk", _SDK_PATH)
if _SDK_SPEC is None or _SDK_SPEC.loader is None:
	raise ImportError(f"Unable to load SDK module from {_SDK_PATH}")

_SDK_MODULE = module_from_spec(_SDK_SPEC)
_SDK_SPEC.loader.exec_module(_SDK_MODULE)

SimeisSDK = _SDK_MODULE.SimeisSDK
SimeisError = _SDK_MODULE.SimeisError