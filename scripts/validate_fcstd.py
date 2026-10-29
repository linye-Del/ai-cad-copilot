"""FreeCAD 端：重新打开 FCStd 文件并验证真实几何（独立进程，从磁盘加载）。

用法（freecadcmd 无头执行）：
    freecadcmd.exe -c "exec(open(r'<本文件>', encoding='utf-8').read())" --pass <fcstd_path> <out_json>

输出 JSON：
    {"ok": true, "solids": N, "volume": V, "faces": N, "edges": N, "vertices": N, "objects": N}
"""

import json
import sys


def main():
    args = [
        a for a in sys.argv[1:]
        if a != "--pass" and not a.startswith("-c") and not a.startswith("exec(open")
    ]
    if len(args) < 2:
        print("缺少参数: fcstd_path out_json", file=sys.stderr)
        sys.exit(1)
    fcstd_path, out_path = args[0], args[1]

    import FreeCAD as App

    result = {"ok": False, "solids": 0, "volume": 0.0, "faces": 0,
              "edges": 0, "vertices": 0, "objects": 0}
    try:
        # 从磁盘重新打开文档（非内存对象，证明 FCStd 真实可加载）
        doc = App.openDocument(fcstd_path)
        shapes = [o for o in doc.Objects if hasattr(o, "Shape") and not o.Shape.isNull()]
        result["objects"] = len(doc.Objects)
        # 选取含 Solid 最多的实体对象（排除 TechDraw 页/模板等辅助对象）
        best = max(shapes, key=lambda o: len(o.Shape.Solids)) if shapes else None
        if best is not None:
            shape = best.Shape
            result["solids"] = len(shape.Solids)
            result["volume"] = round(shape.Volume, 2)
            result["faces"] = len(shape.Faces)
            result["edges"] = len(shape.Edges)
            result["vertices"] = len(shape.Vertexes)
            result["ok"] = True
        App.closeDocument(doc.Name)
    except Exception as e:
        result["error"] = str(e)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
