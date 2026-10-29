import importlib
import sys

PARTS = {}


def load_part_meta() -> dict:
    from config import settings

    parts_dir = str(settings.PARTS_DIR)
    if parts_dir not in sys.path:
        sys.path.insert(0, parts_dir)

    metas = {}
    for py in sorted(settings.PARTS_DIR.glob("*.py")):
        if py.name.startswith("_"):
            continue
        mod = importlib.import_module(py.stem)
        if getattr(mod, "META", None):
            metas[mod.META["key"]] = mod.META
    return metas


def get_part(part_type: str):
    return importlib.import_module(f"cad_engine.parts.{part_type}")


PARTS = load_part_meta()