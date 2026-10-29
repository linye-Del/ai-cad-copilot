"""零件类型注册表：从 parts 模块加载 META 并执行参数补全(derive)。"""

import importlib

PART_KEYS = ["bolt", "shaft", "flange", "gear"]


def _load(key: str):
    return importlib.import_module(f"cad_engine.parts.{key}")


def get_meta(key: str) -> dict:
    return _load(key).META


def all_metas() -> dict:
    return {k: _load(k).META for k in PART_KEYS}


def derive_params(key: str, params: dict) -> dict:
    return _load(key).derive(params)


def part_name_for(key: str, params: dict) -> str:
    meta = get_meta(key)
    if key == "bolt":
        return f"M{params.get('d', '')}x{params.get('L', '')}{meta['name']}"
    if key == "shaft":
        segs = params.get("segments") or []
        if segs:
            return f"阶梯轴_{len(segs)}段"
        return "阶梯轴"
    if key == "flange":
        return f"法兰盘_D{params.get('D', '')}"
    if key == "gear":
        return f"齿轮_m{params.get('m', '')}z{params.get('z', '')}"
    return meta["name"]