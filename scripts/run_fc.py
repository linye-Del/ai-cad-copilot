"""FreeCAD 端入口：读取参数 JSON，建模、导出 STEP/STL/工程图，输出 result.json。"""

import json
import os
import sys
import traceback

REPO_DIR = os.environ.get("FCC_REPO") or (
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in globals() else os.getcwd()
)
sys.path.insert(0, os.path.join(REPO_DIR, "cad_engine", "parts"))
sys.path.insert(0, os.path.join(REPO_DIR, "scripts"))

import FreeCAD as App
import Mesh
import Part

from techdraw import make_drawing


def _try_png(doc, png_path):
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import FreeCADGui as Gui

        Gui.showMainWindow()
        view = Gui.ActiveDocument.ActiveView
        view.viewIsometric()
        view.viewFront()
        view.viewIsometric()
        view.saveImage(png_path, 900, 700)
        return True
    except Exception:
        return False


def _stage(out_dir, name):
    with open(os.path.join(out_dir, "_stage.txt"), "w", encoding="utf-8") as f:
        f.write(name)


def main():
    args = [
        a
        for a in sys.argv[1:]
        if a != "--pass" and not a.startswith("-c") and not a.startswith("exec(open")
    ]
    if len(args) < 2:
        with open(os.path.join(os.path.dirname(args[0]) if args else ".", "result.json"), "w", encoding="utf-8") as f:
            json.dump({"ok": False, "errors": ["缺少参数: params_json out_dir"]}, f, ensure_ascii=False)
        return
    params_json = args[0]
    out_dir = args[1]
    result = {"ok": False, "files": {}, "drawing": {}, "errors": []}
    try:
        with open(params_json, "r", encoding="utf-8-sig") as f:
            spec = json.load(f)
        ptype = spec["part_type"]
        params = spec["params"]
        name = spec["part_name"]

        doc = App.newDocument('CADPart')
        _stage(out_dir, 'build')
        mod = __import__(ptype, fromlist=["*"])
        if hasattr(mod, "derive"):
            params = mod.derive(params)
        feature = mod.build(doc, params)
        doc.recompute()

        _stage(out_dir, 'export')
        base = os.path.join(out_dir, ptype)
        result["display_name"] = name
        fcstd = base + ".FCStd"
        doc.saveAs(fcstd)
        result["files"]["fcstd"] = fcstd

        shape = feature.Shape
        step = base + ".step"
        shape.exportStep(step)
        result["files"]["step"] = step

        stl = base + ".stl"
        mesh = Mesh.Mesh(shape.tessellate(0.2))
        mesh.write(stl)
        result["files"]["stl"] = stl

        _stage(out_dir, 'drawing')
        drawing = make_drawing(doc, feature, params, ptype, base)
        result["drawing"] = drawing

        doc.recompute()
        doc.saveAs(fcstd)
        _stage(out_dir, 'save2')

        png = base + ".png"
        if os.environ.get("FCC_TRY_PNG") == "1" and _try_png(doc, png):
            result["files"]["png"] = png

        result["ok"] = True
    except Exception:
        result["errors"].append(traceback.format_exc())

    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
