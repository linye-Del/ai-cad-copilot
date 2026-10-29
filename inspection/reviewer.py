"""工程图审查 reviewer：解析 DXF/PDF/SVG 工程图，校验与零件参数的一致性。

输出问题格式统一为 {problem, location, risk, suggestion}：
- problem: 问题描述
- location: 在图纸中的位置（视图/区域）
- risk: 风险等级 high/medium/low
- suggestion: 修改建议
"""

import os
import re

# 数字提取：支持 "φ160"、"M10"、"10×40"、"25" 等
_NUM_RE = re.compile(r"[\d]+(?:\.\d+)?")

_LEVEL_CN = {"high": "高风险", "medium": "中风险", "low": "低风险"}


def _issue(problem, location, risk, suggestion):
    return {"problem": problem, "location": location, "risk": risk,
            "risk_cn": _LEVEL_CN.get(risk, risk), "suggestion": suggestion}


# ---------- DXF ----------

def _parse_dxf(path):
    """用 ezdxf 解析 DXF，返回实体统计与标注文本。"""
    import ezdxf

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    texts = []
    circles = lines = 0
    for e in msp:
        if e.dxftype() in ("TEXT", "MTEXT"):
            t = e.dxf.text if e.dxftype() == "TEXT" else e.text
            texts.append(t.replace("\n", " "))
        elif e.dxftype() == "CIRCLE":
            circles += 1
        elif e.dxftype() == "LINE":
            lines += 1
    return {"texts": texts, "circles": circles, "lines": lines}


# ---------- PDF ----------

def _parse_pdf(path):
    """用 pymupdf 提取 PDF 文本与图形数量。"""
    import pymupdf

    doc = pymupdf.open(path)
    texts = []
    circles = lines = 0
    for page in doc:
        texts.append(page.get_text())
        for d in page.get_drawings():
            for item in d["items"]:
                if item[0] == "c":
                    circles += 1
                elif item[0] == "l":
                    lines += 1
    return {"texts": texts, "circles": circles, "lines": lines}


# ---------- SVG ----------

def _parse_svg(path):
    """提取 SVG 中的文本标注与图形数量。"""
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    texts = []
    circles = lines = 0
    ns = {"svg": "http://www.w3.org/2000/svg"}
    for t in root.iter("{http://www.w3.org/2000/svg}text"):
        texts.append((t.text or "").strip())
    for c in root.iter("{http://www.w3.org/2000/svg}circle"):
        circles += 1
    for c in root.iter("{http://www.w3.org/2000/svg}line"):
        lines += 1
    return {"texts": texts, "circles": circles, "lines": lines}


_PARSERS = {".dxf": _parse_dxf, ".pdf": _parse_pdf, ".svg": _parse_svg}


# ---------- 一致性检查 ----------

def _all_params(spec):
    """展平所有参数值（含派生、分段），返回 {字段名: 数值}。"""
    out = {}
    params = spec.get("params", {}) or {}
    for k, v in params.items():
        if k == "derived" and isinstance(v, dict):
            out.update(v)
        elif isinstance(v, (int, float)):
            out[k] = float(v)
        elif isinstance(v, list):
            for i, seg in enumerate(v):
                if isinstance(seg, dict):
                    for sk, sv in seg.items():
                        if isinstance(sv, (int, float)):
                            out[f"{k}{i+1}_{sk}"] = float(sv)
    return out


def _find_in_texts(texts, value, label):
    """在图纸文本中查找尺寸值；找不到时返回未标注问题。"""
    target = f"{value:g}"
    for t in texts:
        if target in t:
            return None
    return _issue(f"图纸中未找到 {label} 的标注（应标 {target}）", "标注区", "medium",
                  f"补充 {label}={target} 的尺寸标注")


def check_consistency(spec, texts, has_circles):
    """校验标注与参数一致性。"""
    issues = []
    ptype = spec.get("part_type", "")
    params = spec.get("params", {}) or {}
    all_p = _all_params(spec)

    if ptype == "bolt":
        for key, label in [("d", "公称直径 d"), ("L", "长度 L"), ("b", "螺纹长度 b")]:
            if key in all_p:
                issues.append(_find_in_texts(texts, all_p[key], label))
    elif ptype == "shaft":
        for key in sorted(all_p):
            if key.startswith("segments") and key.endswith("_L"):
                issues.append(_find_in_texts(texts, all_p[key], key.replace("segments", "轴段").replace("_L", "长度")))
        if "segments1_L" in all_p and "总长" not in " ".join(texts):
            total = sum(v for k, v in all_p.items() if k.startswith("segments") and k.endswith("_L"))
            issues.append(_find_in_texts(texts, total, "总长"))
    elif ptype == "flange":
        for key, label in [("D", "外径 D"), ("d", "内径 d"), ("t", "厚度 t"), ("pcd", "分度圆 PCD")]:
            if key in all_p:
                issues.append(_find_in_texts(texts, all_p[key], label))
    elif ptype == "gear":
        da = params.get("derived", {}).get("da")
        for key, label in [("m", "模数 m"), ("z", "齿数 z"), ("b", "齿宽 b"), ("d_hub", "孔径 d_hub")]:
            if key in all_p:
                issues.append(_find_in_texts(texts, all_p[key], label))
        if da:
            issues.append(_find_in_texts(texts, da, "齿顶圆直径 da"))

    # 视图完整性
    if not has_circles and ptype in ("flange", "gear"):
        issues.append(_issue("端面视图（圆）缺失，无法确认回转体轮廓", "视图区", "high",
                             "补充端面视图，标注外径/内径/孔分布"))
    return [i for i in issues if i]


# ---------- 主入口 ----------

def review_drawing(path: str, spec: dict) -> dict:
    """审查工程图文件，返回 {problems: [...], passed: bool}。"""
    ext = os.path.splitext(path)[1].lower()
    parser = _PARSERS.get(ext)
    if not parser:
        return {"problems": [_issue(f"不支持的文件格式 {ext}（支持 DXF/PDF/SVG）", "文件", "high",
                                    "导出为 DXF/PDF/SVG 后重试")], "passed": False}
    if not os.path.isfile(path):
        return {"problems": [_issue(f"工程图文件不存在: {path}", "文件", "high", "检查输出目录")],
                "passed": False}
    try:
        parsed = parser(path)
    except ImportError as e:
        package = getattr(e, "name", "") or "optional parser"
        hint = ("安装可选 PDF 依赖：pip install -r requirements-pdf.txt"
                if package in {"pymupdf", "fitz"}
                else "安装对应文件格式的可选依赖后重试")
        return {"problems": [_issue(
            f"解析工程图缺少可选依赖 {package}", "文件", "high", hint)],
            "passed": False, "error": "missing_optional_dependency"}
    except Exception as e:
        return {"problems": [_issue(f"解析工程图失败: {e}", "文件", "high", "检查文件完整性")],
                "passed": False}

    texts = parsed["texts"]
    has_circles = parsed["circles"] > 0
    problems = check_consistency(spec, texts, has_circles)

    if not texts:
        problems.append(_issue("工程图未提取到任何文字标注，无法校验尺寸", "标注区", "medium",
                               "确认工程图含尺寸标注后重新审查"))
    elif not problems:
        pass  # 尺寸标注齐全

    return {"problems": problems, "passed": len(problems) == 0,
            "ext": ext, "texts_found": len(texts), "circles": parsed["circles"]}
