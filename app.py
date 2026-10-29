"""AI CAD Copilot - Streamlit 主界面。"""

import base64
import json
import os

import pandas as pd
import streamlit as st

from cad_engine import runner
from inspection import llm_check, rules as rule_checker
from agent import parser, schema
from config import settings

st.set_page_config(page_title="AI CAD Copilot - 智能机械设计", layout="wide")

EXAMPLES = []
for meta in schema.all_metas().values():
    EXAMPLES.extend(meta.get("examples", []))


def env_check() -> list:
    rows = []
    rows.append(("Python", "OK"))
    fc = runner.find_freecad()
    rows.append(("FreeCADCmd", fc if fc else "未找到"))
    rows.append(("DeepSeek API Key", "已配置" if settings.get_api_key() else "未配置(使用规则解析)"))
    rows.append(("输出目录", str(settings.OUTPUT_DIR)))
    return rows


def stl_viewer_html(stl_path: str, height: int = 460) -> str:
    with open(stl_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"""
<div id="fc-viewer" style="width:100%;height:{height}px;background:#1a1d24;border-radius:8px;"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js"></script>
<script>
(function(){{
var container = document.getElementById('fc-viewer');
var scene = new THREE.Scene();
var camera = new THREE.PerspectiveCamera(45, container.clientWidth/container.clientHeight, 0.1, 2000);
camera.position.set(120, 90, 160);
var renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.setPixelRatio(window.devicePixelRatio);
container.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
var dl = new THREE.DirectionalLight(0xffffff, 0.9); dl.position.set(150, 200, 120); scene.add(dl);
var dl2 = new THREE.DirectionalLight(0xffffff, 0.35); dl2.position.set(-120, -60, -80); scene.add(dl2);
var grid = new THREE.GridHelper(260, 20, 0x4a5568, 0x374151); grid.position.y = -0.01; scene.add(grid);
var loader = new THREE.STLLoader();
var bytes = Uint8Array.from(atob('{b64}'), c => c.charCodeAt(0));
var geo = loader.parse(bytes);
geo.computeVertexNormals();
geo.center();
var mat = new THREE.MeshStandardMaterial({color:0x7ea6e0, metalness:0.35, roughness:0.45, flatShading:false});
var mesh = new THREE.Mesh(geo, mat); scene.add(mesh);
var controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.autoRotate = true; controls.autoRotateSpeed = 1.6;
var axes = new THREE.AxesHelper(40); scene.add(axes);
function tick(){{ requestAnimationFrame(tick); controls.update(); renderer.render(scene, camera); }}
tick();
window.addEventListener('resize', function(){{ camera.aspect = container.clientWidth/container.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(container.clientWidth, container.clientHeight); }});
}})();
</script>
"""


def render_param_editor(meta: dict, params: dict) -> dict:
    st.subheader(f"{meta['name']} 参数确认（可修改）")
    edited = dict(params)
    for f in meta["fields"]:
        fname = f["name"]
        label = f"{f['label']} ({f['unit']})" if f.get("unit") else f["label"]
        ftype = f.get("type", "number")
        if ftype == "list":
            item_fields = f["item_fields"]
            rows = edited.get(fname) or []
            df = pd.DataFrame(rows) if rows else pd.DataFrame(
                [{fi["name"]: fi.get("default", 0.0) for fi in item_fields}]
            )
            st.markdown(f"**{label}**")
            out = st.data_editor(
                df,
                num_rows="dynamic",
                key=f"editor_{fname}",
                use_container_width=True,
                column_config={
                    fi["name"]: st.column_config.NumberColumn(fi["label"], min_value=0.0, format="%.1f")
                    for fi in item_fields
                },
            )
            edited[fname] = out.to_dict("records")
            if f.get("help"):
                st.caption(f["help"])
        elif ftype == "group":
            gv = edited.get(fname) or {}
            with st.expander(f["label"], expanded=False):
                for gf in f["fields"]:
                    gname = gf["name"]
                    gtype = gf.get("type", "text")
                    gval = gv.get(gname, gf.get("default", ""))
                    if gtype == "bool":
                        gv[gname] = st.checkbox(gf["label"], value=bool(gval), key=f"grp_{fname}_{gname}")
                    else:
                        suffix = f" ({gf['unit']})" if gf.get("unit") else ""
                        gv[gname] = st.number_input(gf["label"] + suffix, value=float(gval), key=f"grp_{fname}_{gname}")
                edited[fname] = gv
        else:
            cols = st.columns(3)
            with cols[0]:
                cur = edited.get(fname, f.get("default", 0.0))
                if ftype == "text":
                    edited[fname] = st.text_input(label, value=str(cur) if cur is not None else "", key=f"p_{fname}")
                elif ftype == "bool":
                    edited[fname] = st.checkbox(label, value=bool(cur), key=f"p_{fname}")
                else:
                    edited[fname] = st.number_input(label, value=float(cur or 0.0), key=f"p_{fname}")
            with cols[1]:
                if f.get("help"):
                    st.caption(f["help"])
    return edited


def show_issues(issues: list, title: str = "检测结果"):
    if not issues:
        st.success("未发现明显问题")
        return
    colors = {"error": "🔴", "warning": "🟡", "info": "🔵"}
    df = pd.DataFrame(
        [
            {
                "级别": colors.get(i["level"], "⚪"),
                "问题项": i["item"],
                "描述": i["detail"],
                "建议": i["suggestion"],
            }
            for i in issues
        ]
    )
    st.markdown(f"**{title}**（共 {len(issues)} 项）")
    st.dataframe(df, use_container_width=True, hide_index=True)


def show_result(result: dict):
    files = result.get("files", {})
    drawing = result.get("drawing", {})
    col1, col2 = st.columns([3, 2])
    with col1:
        st.subheader("3D 模型预览")
        if files.get("stl") and os.path.isfile(files["stl"]):
            st.components.v1.html(stl_viewer_html(files["stl"]), height=480)
        elif files.get("png") and os.path.isfile(files["png"]):
            st.image(files["png"], use_container_width=True)
        else:
            st.warning("无 3D 预览（可下载 STEP 用专业软件查看）")
    with col2:
        st.subheader("生成文件")
        for key, label in [("fcstd", "FreeCAD 源文件 (.FCStd)"), ("step", "STEP 三维模型"), ("stl", "STL 网格")]:
            p = files.get(key)
            if p and os.path.isfile(p):
                with open(p, "rb") as f:
                    st.download_button(label, f.read(), file_name=os.path.basename(p), use_container_width=True)
        for key, label in [("svg", "工程图 SVG"), ("pdf", "工程图 PDF"), ("dxf", "工程图 DXF")]:
            p = drawing.get(key)
            if p and os.path.isfile(p):
                with open(p, "rb") as f:
                    st.download_button(label, f.read(), file_name=os.path.basename(p), use_container_width=True)

    st.subheader("工程图预览")
    if drawing.get("svg") and os.path.isfile(drawing["svg"]):
        with open(drawing["svg"], encoding="utf-8") as f:
            svg = f.read()
        st.components.v1.html(f'<div style="background:#fff;padding:8px;border-radius:8px">{svg}</div>', height=720, scrolling=True)
    elif drawing.get("pdf") and os.path.isfile(drawing["pdf"]):
        with open(drawing["pdf"], "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        st.components.v1.html(
            f'<iframe src="data:application/pdf;base64,{b64}" style="width:100%;height:720px;border:none"></iframe>',
            height=740,
        )
    else:
        st.warning("工程图导出失败：" + drawing.get("error", "未知原因"))

    if result.get("errors"):
        with st.expander("FreeCAD 日志（调试用）"):
            st.code("\n".join(result["errors"]), language="text")


def main():
    st.title("AI CAD Copilot - 智能机械设计助手")
    st.caption("自然语言描述 → FreeCAD 三维模型 + 工程图 + AI 图纸错误检测  |  智能制造方向求职演示")

    with st.sidebar:
        st.header("运行配置")
        api_key = st.text_input("DeepSeek API Key", value=settings.get_api_key(), type="password")
        model = st.text_input("模型", value=settings.get_model())
        fc_bin = st.text_input("FreeCADCmd 路径", value=runner.find_freecad())
        if st.button("环境自检", use_container_width=True):
            for k, v in env_check():
                st.markdown(f"- **{k}**: {v}")
        st.divider()
        st.markdown("**示例语句**")
        for ex in EXAMPLES:
            if st.button(ex, use_container_width=True, key=f"ex_{ex[:12]}"):
                st.session_state["nl_text"] = ex

    tab1, tab2, tab3 = st.tabs(["智能零件生成", "AI 图纸审查", "关于本项目"])

    with tab1:
        nl = st.text_area(
            "输入自然语言零件描述",
            value=st.session_state.get("nl_text", ""),
            height=110,
            placeholder="例如：生成一个M10×40的六角头螺栓，8.8级，螺纹长度25mm，材料40Cr，表面发黑",
        )
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("解析参数", type="primary", use_container_width=True):
                if not nl.strip():
                    st.warning("请先输入零件描述")
                else:
                    with st.spinner("大模型解析中..."):
                        try:
                            spec = parser.parse(nl.strip(), api_key, settings.get_api_base(), model)
                            spec["params"] = schema.derive_params(spec["part_type"], spec["params"])
                            st.session_state["spec"] = spec
                            st.session_state["result"] = None
                        except Exception as e:
                            st.error(f"解析失败：{e}")
        with c2:
            st.caption("支持：六角头螺栓 / 阶梯轴 / 法兰盘 / 直齿圆柱齿轮。未配置 API Key 时自动使用规则引擎。")

        spec = st.session_state.get("spec")
        if spec:
            st.info(f"识别结果：**{spec['part_type']}** - {spec['part_name']}（来源：{spec['source']}）")
            meta = schema.get_meta(spec["part_type"])
            edited = render_param_editor(meta, spec["params"])
            if st.button("补全派生参数", key="derive_btn"):
                edited = schema.derive_params(spec["part_type"], edited)
            spec["params"] = edited

            derived = spec["params"].get("derived")
            if derived:
                st.subheader("派生尺寸（自动计算）")
                st.dataframe(
                    pd.DataFrame(
                        [{"参数": k, "数值": v} for k, v in derived.items()],
                        columns=["参数", "数值"],
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            if st.button("生成 3D 模型 + 工程图", type="primary", use_container_width=True):
                with st.spinner("FreeCAD 建模中（首次运行稍慢）..."):
                    try:
                        result = runner.run(st.session_state["spec"])
                        st.session_state["result"] = result
                    except Exception as e:
                        st.error(f"生成失败：{e}")
                        st.code(str(e), language="text")

            result = st.session_state.get("result")
            if result:
                if result.get("ok"):
                    st.success("模型与工程图生成成功")
                    show_result(result)
                    issues = rule_checker.check(spec["part_type"], spec["params"]) + rule_checker.check_outputs(result)
                    show_issues(issues, "规则检查（参数 + 输出完整性）")
                else:
                    st.error("FreeCAD 执行失败")
                    show_result(result)

    with tab2:
        parts = []
        out_root = settings.OUTPUT_DIR
        if out_root.is_dir():
            for d in sorted(out_root.iterdir(), reverse=True):
                rp = d / "result.json"
                pp = d / "params.json"
                if rp.is_file() and pp.is_file():
                    try:
                        with open(pp, encoding="utf-8") as f:
                            spec = json.load(f)
                        parts.append((str(d), spec.get("part_name", d.name), spec))
                    except Exception:
                        continue
        if not parts:
            st.info("暂无已生成零件，请先在「智能零件生成」中生成。")
        else:
            sel = st.selectbox("选择零件", parts, format_func=lambda x: x[1])
            out_dir, name, spec = sel
            ptype = spec["part_type"]
            params = spec.get("params", {})
            meta = schema.get_meta(ptype)
            st.markdown(f"**{meta['name']}** | {name} | 目录: `{out_dir}`")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("运行规则检查", type="primary", use_container_width=True):
                    st.session_state["rule_issues"] = rule_checker.check(ptype, params)
            with c2:
                if st.button("AI 深度审查（DeepSeek）", use_container_width=True):
                    with st.spinner("大模型审查中..."):
                        rule_issues = rule_checker.check(ptype, params)
                        res = llm_check.llm_review(ptype, params, rule_issues, api_key, settings.get_api_base(), model)
                        st.session_state["llm_issues"] = res.get("issues", [])
                        if res.get("error"):
                            st.warning(f"LLM 审查失败：{res['error']}")
            if "rule_issues" in st.session_state:
                show_issues(st.session_state["rule_issues"], "规则检查结果")
            if st.session_state.get("llm_issues"):
                show_issues(st.session_state["llm_issues"], "AI 深度审查结果")
            rp = os.path.join(out_dir, "result.json")
            if os.path.isfile(rp):
                with open(rp, encoding="utf-8") as f:
                    result = json.load(f)
                out_issues = rule_checker.check_outputs(result)
                if out_issues:
                    show_issues(out_issues, "输出完整性检查")

    with tab3:
        st.markdown(
            """
### 项目简介
AI CAD Copilot 将**大语言模型（DeepSeek）**与 **FreeCAD 参数化建模**结合：
- 自然语言描述机械零件 → LLM 抽取结构化参数
- 自动生成三维模型（螺栓/阶梯轴/法兰/直齿轮，含标准派生尺寸）
- 自动生成工程图（TechDraw 三视图 + 尺寸标注 + 标题栏）
- 规则引擎 + LLM 双重图纸错误检测（GB/T 标准符合性、工艺性、强度隐患）

### 技术架构
```
用户输入自然语言
   │
   ▼
[DeepSeek LLM] 参数抽取 ── 无 Key 时回退规则引擎
   │ 结构化参数 JSON
   ▼
[FreeCADCmd 无头] 参数化建模 ── 螺栓/阶梯轴/法兰/齿轮
   │ 导出 FCStd / STEP / STL
   ▼
[TechDraw] 三视图 + 尺寸标注 + 标题栏 ── SVG / PDF / DXF
   │
   ▼
[检测模块] 规则引擎(GB/T) + DeepSeek 深度审查
   │
   ▼
[Streamlit] 3D 交互预览 + 工程图预览 + 下载
```

### 技术栈
Python · Streamlit · DeepSeek API · FreeCAD 1.1 (Part/TechDraw/Mesh) · Pydantic

### 运行方式
```bash
pip install -r requirements.txt
streamlit run app.py
```
            """
        )


if __name__ == "__main__":
    main()