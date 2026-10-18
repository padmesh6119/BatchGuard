"""Check the actual deployment environment without changing it or downloading packages."""
import importlib
import importlib.util
import json
from pathlib import Path
import platform
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check():
    errors = []
    if platform.machine().lower() != "s390x":
        errors.append("Requires a real s390x execution host")
    packages = {}
    for module in ("numpy", "scipy", "pandas", "sklearn", "openpyxl", "matplotlib"):
        try:
            loaded = importlib.import_module(module)
            packages[module] = getattr(loaded, "__version__", "available")
        except ImportError as exc:
            errors.append(f"{module}: {exc}")
    packages["snapml"] = "available" if importlib.util.find_spec("snapml") else "optional backend not installed"
    if not errors:
        try:
            from src.fusion import load_models
            from src.layer_a import load_dataset
            from sklearn.exceptions import InconsistentVersionWarning
            with warnings.catch_warnings():
                warnings.simplefilter("error", InconsistentVersionWarning)
                if load_models("sklearn") is None:
                    errors.append("No trained scikit-learn model; run python -m src.fusion run")
            load_dataset()
        except Exception as exc:
            errors.append(f"Artifact validation: {type(exc).__name__}: {exc}")
    return {"machine": platform.machine(), "python": platform.python_version(),
            "packages": packages, "ready": not errors, "errors": errors,
            "next": "Launch the loopback service through an SSH tunnel. Snap ML is optional."}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["ready"] else 2)
