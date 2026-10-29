"""机械设计决策系统：四大类别规则实现。

类别：
- manufacturing 加工工艺（倒角/圆角/退刀槽/加工可达性）
- strength     强度校核（轴径推荐/应力集中/壁厚）
- assembly     装配配合（间隙/配合/轴承安装）
- standards    标准符合性（GB/T、ISO）

每条规则含 condition（触发判定）、analysis（工程解释）、
risk（风险等级）、recommendation（建议）、standard（依据标准）。
"""

import math

from knowledge_base.rules import Rule, register
from knowledge_base import gbt

# ---------------------------------------------------------------- 加工工艺

register(Rule(
    id="mf_chamfer_missing",
    cause="端部尖角无引导且毛刺未去除",
    consequence="装配刮伤配合面，尖角应力集中，运输操作划伤风险",
    category="manufacturing", name="轴端/孔口未倒角",
    condition=lambda p: p.get("chamfer", 0) in (None, 0, ""),
    analysis="零件端部未倒角：装配时易刮伤配合面、产生毛刺尖角，应力集中且不符合机械加工工艺习惯。"
             "倒角同时起到去毛刺、引导装配、降低切口应力作用。",
    risk="medium", level="warning", standard="GB/T 6403.4-2008（倒角尺寸 0.2~5mm）",
    recommendation="轴端、孔口增加 C0.5~C2 倒角；螺纹端部倒角不小于螺距的 0.5 倍。",
    applies_to=["shaft", "flange"],
))

register(Rule(
    id="mf_chamfer_oversize",
    cause="倒角过大显著减小有效承载截面",
    consequence="承载能力下降，轴向定位精度受影响",
    category="manufacturing", name="倒角尺寸过大",
    condition=lambda p: float(p.get("chamfer", 0) or 0) > 3
                        and min(float(s.get("d", 99)) for s in (p.get("segments") or [{"d": 50}]) if s.get("d", 0) > 0) < 20,
    analysis="小直径轴段上过大的倒角会显著减少有效承载截面，且倒角面过大影响零件的轴向定位精度。",
    risk="low", level="info", standard="GB/T 6403.4-2008",
    recommendation="小径段（d<20mm）倒角建议 ≤C1.5，仅去毛刺需求可用 C0.5。",
    applies_to=["shaft"],
))

register(Rule(
    id="mf_fillet_stress",
    cause="直径突变处直角过渡，应力线急剧集中（Kt 可达 2.5 以上）",
    consequence="疲劳寿命降低，交变载荷下轴肩根部萌生裂纹",
    category="manufacturing", name="轴肩过渡未设圆角",
    condition=lambda p: (p.get("fillet", 0) or 0) <= 0 and _max_step_diff(p) >= 3,
    analysis="台阶轴在直径变化处若为直角过渡，应力集中系数 Kt 可达 2.5 以上；"
             "设置圆角 R≥0.5×(Δd) 可将 Kt 降至 1.5 以下，显著提高疲劳强度。",
    risk="medium", level="warning", standard="GB/T 6403.4-2008（零件倒角与圆角）",
    recommendation="轴肩过渡处设圆角 R≥0.5×(相邻直径差)，通常取 R1~R3。",
    applies_to=["shaft"],
))

register(Rule(
    id="mf_relief_groove",
    cause="磨削砂轮无法清根，产生磨削台阶与残余拉应力",
    consequence="轴承内圈端面无法贴实定位，轴肩根部应力集中",
    category="manufacturing", name="磨削面未设退刀槽",
    condition=lambda p: (p.get("fillet", 0) or 0) == 0 and _max_step_diff(p) >= 5,
    analysis="轴承位等磨削表面与相邻轴肩直角相接时，砂轮无法清根，会产生磨削台阶与残余应力，"
             "且装配时轴承内圈端面无法贴实定位。",
    risk="low", level="info", standard="GB/T 6403.5-2008（退刀槽形式与尺寸）",
    recommendation="轴肩根部预留退刀槽（宽 2~3mm、深 0.5~1mm），或采用砂轮越程槽。",
    applies_to=["shaft"],
))

register(Rule(
    id="mf_deep_hole",
    cause="深径比过大，钻头刚度不足易偏斜，排屑困难",
    consequence="孔径公差与位置度超差，加工成本上升",
    category="manufacturing", name="深孔加工可达性差",
    condition=lambda p: float(p.get("t", 0) or 0) > 0
                        and float(p.get("hole_d", 11) or 0) > 0
                        and float(p.get("t")) / float(p.get("hole_d")) > 8,
    analysis="法兰厚度与孔径比 L/d>8 时属于深孔钻削，钻头刚度不足易偏斜，"
             "孔径公差与位置度难以保证，需要多次进退刀排屑。",
    risk="medium", level="warning", standard="GB/T 1804 / 工艺手册（深径比 L/d≤5 为浅孔）",
    recommendation="增大孔径、分段钻孔（阶梯孔）或改用加工中心铣削，控制深径比 ≤5~6。",
    applies_to=["flange"],
))

register(Rule(
    id="mf_keyway_end",
    cause="键槽端部尖角处应力集中，铣刀加工易崩边",
    consequence="键槽端部开裂，键连接失效",
    category="manufacturing", name="键槽距轴端过近",
    condition=lambda p: _keyway(p) and _keyway_end_margin(p) < 5,
    analysis="键槽延伸至轴端过近处，端部尖角处应力集中显著，且铣刀加工时易崩边；"
             "GB/T 1095 要求键槽两端留足工艺余量。",
    risk="medium", level="warning", standard="GB/T 1095-2003（平键键槽尺寸与公差）",
    recommendation="键槽两端距轴端至少留 5~10mm，或缩短键长。",
    applies_to=["shaft"],
))

# ---------------------------------------------------------------- 强度校核

register(Rule(
    id="st_torsion_check",
    cause="轴端直径小于满足许用扭转切应力的最小直径，材料截面抗扭能力不足",
    consequence="电机启动/堵转冲击下轴可能发生扭断或塑性扭转变形，导致传动失效",
    category="strength", name="扭转强度校核",
    condition=lambda p: _torsion_fail(p),
    analysis="按扭转强度条件 τ_max=16T/(πd³) ≤ [τ] 校核：当前轴端直径小于满足材料许用"
             "扭转切应力所需的最小直径，电机启动/堵转冲击下可能扭断或塑性变形。",
    risk="high", level="error", standard="GB/T 699（材料力学性能）/ 机械设计手册",
    recommendation="增大最小轴径至满足 τ=16T/(πd³)≤[τ]，或改用高强度材料（40Cr 调质 [τ]≈55MPa）。",
    applies_to=["shaft"], needs_torque=True,
))

register(Rule(
    id="st_keyway_depth",
    cause="键槽削弱了轴的抗扭截面（单键槽削弱系数约 0.93~0.96），应力集中叠加",
    consequence="交变扭矩下键槽端部萌生裂纹，轴疲劳寿命显著下降",
    category="strength", name="键槽深度占比过大",
    condition=lambda p: _keyway(p) and (float(p["keyway"]["t"]) / float(_keyway_seg(p)["d"])) > 0.12,
    analysis="键槽深度 t 与轴径 d 之比超过 0.12 时，轴的抗扭截面系数损失显著"
             "（单键槽削弱系数约 0.93~0.96），应力集中叠加后疲劳强度明显下降。",
    risk="medium", level="warning", standard="GB/T 1095-2003（键槽深与轴径匹配表）",
    recommendation="按 GB/T 1095 选择键规格（查表匹配轴径的槽深），或加大轴径、改花键连接。",
    applies_to=["shaft"],
))

register(Rule(
    id="st_keyway_length",
    cause="键槽过长使键与键槽接触应力分布不均，端部应力集中",
    consequence="键连接早期失效，键槽端部开裂",
    category="strength", name="键槽长度接近轴段全长",
    condition=lambda p: _keyway(p) and (float(p["keyway"].get("lk", 0)) / float(_keyway_seg(p).get("L", 1))) > 0.9,
    analysis="键槽长度占轴段长度 90% 以上时，键与键槽的实际接触应力分布不均，"
             "且轴段端部键槽削弱了截面的弯曲强度。",
    risk="low", level="info", standard="GB/T 1095-2003",
    recommendation="键长按传递扭矩计算后取 0.8×L 左右即可，必要时双键 180° 布置。",
    applies_to=["shaft"],
))

register(Rule(
    id="st_wall_thin",
    cause="法兰环带过薄，螺栓预紧力引起的环向应力与弯曲应力叠加",
    consequence="密封面变形导致泄漏，螺栓孔边缘开裂",
    category="strength", name="法兰壁厚过薄",
    condition=lambda p: (float(p.get("D", 0)) - float(p.get("d", 0))) / 2 < 6,
    analysis="法兰环带壁厚小于 6mm 时，螺栓预紧力引起的环向应力与弯曲应力叠加，"
             "刚性不足会导致密封面变形、螺栓孔边缘开裂。",
    risk="medium", level="warning", standard="GB/T 9116（法兰壁厚经验值）",
    recommendation="增大外径或减小内径，使壁厚 ≥6mm（高压工况 ≥10mm）。",
    applies_to=["flange"],
))

register(Rule(
    id="st_rim_thin",
    cause="轮缘厚度不足，齿根弯曲应力与毂孔过盈应力联合作用",
    consequence="轮缘开裂，齿轮早期失效",
    category="strength", name="齿轮轮缘厚度不足",
    condition=lambda p: _gear_rim(p) is not None and _gear_rim(p) < 0.8 * float(p.get("m", 2.5)),
    analysis="齿根圆到毂孔之间的轮缘厚度不足 0.8 倍模数时，轮缘在齿根弯曲应力与"
             "毂孔过盈配合应力联合作用下易开裂。",
    risk="high", level="error", standard="GB/T 1357（齿轮轮缘经验约束）",
    recommendation="加大模数/齿数（增大齿根圆）或减小毂孔径，保证轮缘厚度 ≥0.8m。",
    applies_to=["gear"],
))

register(Rule(
    id="st_slender_shaft",
    cause="长径比过大，弯曲刚度与临界转速下降",
    consequence="高速工况下可能共振，挠度过大影响齿轮啮合与轴承寿命",
    category="strength", name="细长轴挠度风险",
    condition=lambda p: _slenderness(p) > 20,
    analysis="轴的长径比超过 20 时属于细长轴：扭转刚度与弯曲刚度下降，"
             "高速工况下可能产生共振（临界转速需校核），挠度过大影响齿轮啮合与轴承寿命。",
    risk="medium", level="info", standard="机械设计手册（长径比 L/d>20 需挠度校核）",
    recommendation="增大轴径、增加中间支承，或校核临界转速（n_cr≈950√(1/δ) rpm）。",
    applies_to=["shaft"],
))

register(Rule(
    id="st_segment_short",
    cause="轴段承载长度不足，键/花键连接强度与接触应力超标",
    consequence="轴上零件安装不稳，连接早期失效",
    category="strength", name="轴段长度小于直径",
    condition=lambda p: _short_segments(p),
    analysis="轴段长度小于其直径的 2/3 时，该段承载长度不足：键/花键连接强度不够，"
             "或零件（轴承、齿轮）轴向安装空间紧张。",
    risk="medium", level="warning", standard="机械设计手册（轴段长径比经验）",
    recommendation="加长该轴段至 ≥2d/3，或减小该段直径以匹配负载。",
    applies_to=["shaft"],
))

# ---------------------------------------------------------------- 装配配合

register(Rule(
    id="as_bearing_shoulder",
    cause="轴肩高度不满足轴承内圈定位要求（0.035d~0.15d）",
    consequence="轴承内圈轴向窜动，运行噪声与温升增大",
    category="assembly", name="轴肩高度不满足轴承定位",
    condition=lambda p: _bearing_shoulder_low(p),
    analysis="滚动轴承内圈定位轴肩高度 h 应满足 0.035d≤h≤0.15d（GB/T 5868）："
             "h 过小（<0.035d）内圈无法可靠定位，轴向力下内圈会窜动；"
             "h 过大（>0.15d）则轴承拆卸困难。",
    risk="medium", level="warning", standard="GB/T 5868-2003（滚动轴承安装尺寸）",
    recommendation="调整相邻轴段直径差，使轴肩高度 h=Δd/2 落在 0.035d~0.15d 区间。",
    applies_to=["shaft"],
))

register(Rule(
    id="as_fit_recommend",
    cause="未标注配合公差，装配间隙不可控",
    consequence="装配质量波动，旋转件定位精度差",
    category="assembly", name="配合推荐",
    condition=lambda p: True,
    analysis="轴与旋转毂类零件（联轴器/齿轮/带轮）推荐过渡配合 H7/k6 或 H7/m6 定位、"
             "键传递扭矩；滚动轴承内圈与轴推荐 k6/m6（GB/T 1801）；"
             "不标注配合时现场装配质量不可控。",
    risk="low", level="info", standard="GB/T 1801-2009（极限与配合）",
    recommendation="图纸标注：轴-毂 H7/k6；轴承位 k6；非配合面按 ISO 2768-mK 未注公差。",
))

register(Rule(
    id="as_bolt_hole_clearance",
    cause="螺栓孔与内孔之间的环带过窄",
    consequence="螺栓头部与内孔边缘干涉，密封性能受影响",
    category="assembly", name="螺栓孔与内孔间隙不足",
    condition=lambda p: 0 < float(p.get("pcd", 0)) / 2 - float(p.get("d", 0)) / 2 - float(p.get("hole_d", 0)) / 2 < 5,
    analysis="螺栓孔分度圆与内孔之间的环带间隙小于 5mm：螺栓头部/垫圈可能与内孔边缘干涉，"
             "且装配时螺栓孔距内孔过近影响密封。",
    risk="low", level="info", standard="装配工艺经验",
    recommendation="外移分度圆或增大外径，使孔与内孔间隙 ≥5mm。",
    applies_to=["flange"],
))

register(Rule(
    id="as_bearing_seat_len",
    cause="轴承位长度不足以容纳轴承宽度与必要隔套",
    consequence="轴承轴向定位不可靠",
    category="assembly", name="轴承位长度不足",
    condition=lambda p: _bearing_seat_short(p),
    analysis="轴承安装段长度小于 30mm 时无法容纳常用 62/63 系列轴承宽度（B=19~25mm）"
             "与必要的隔套/垫圈，轴向定位不可靠。",
    risk="medium", level="warning", standard="GB/T 276（滚动轴承尺寸系列）",
    recommendation="加长轴承位长度至 ≥B+5mm（如 6209 B=19 → 段长 ≥30mm）。",
    applies_to=["shaft"],
))

# ---------------------------------------------------------------- 标准符合性

register(Rule(
    id="sd_bolt_series",
    cause="直径不在标准系列，非标刀具与扳手不通用",
    consequence="采购成本高，维修互换性差",
    category="standards", name="螺栓直径非标准系列",
    condition=lambda p: round(float(p.get("d", 0))) not in gbt.BOLT_SERIES,
    analysis="公称直径不在 GB/T 5782 常用系列（M6~M36）中，标准件、刀具、扳手不通用，"
             "成本高且可维修性差。",
    risk="medium", level="warning", standard="GB/T 5782-2016（六角头螺栓直径系列）",
    recommendation=f"改用标准直径系列 {sorted(gbt.BOLT_SERIES)} mm。",
    applies_to=["bolt"],
))

register(Rule(
    id="sd_bolt_grade",
    cause="性能等级不在标准系列，材料与热处理无法对应验收",
    consequence="强度保证不可靠，存在失效风险",
    category="standards", name="性能等级不在标准系列",
    condition=lambda p: str(p.get("grade", "")) not in ("", "4.8", "5.8", "6.8", "8.8", "10.9", "12.9"),
    analysis="螺栓性能等级不在 GB/T 3098.1 规定系列中，材料与热处理无法对应验收，"
             "强度保证不可靠。",
    risk="medium", level="warning", standard="GB/T 3098.1-2010（紧固件机械性能）",
    recommendation="常用等级 8.8（40Cr 调质）或 10.9（35CrMo），按载荷校核后选择。",
    applies_to=["bolt"],
))

register(Rule(
    id="sd_module",
    cause="非标模数需定制齿轮刀具（滚刀/插齿刀）",
    consequence="制造成本成倍上升，交期延长",
    category="standards", name="模数非标准系列",
    condition=lambda p: round(float(p.get("m", 0)), 3) not in gbt.STANDARD_MODULES,
    analysis="模数不在 GB/T 1357 标准系列中，齿轮刀具（滚刀/插齿刀）非标定制，"
             "制造成本成倍上升且热处理磨齿余量不易保证。",
    risk="medium", level="warning", standard="GB/T 1357-2008（渐开线圆柱齿轮模数）",
    recommendation=f"改用标准模数 {gbt.STANDARD_MODULES} mm。",
    applies_to=["gear"],
))

register(Rule(
    id="sd_keyway_std",
    cause="轴槽深度未按轴径匹配 GB/T 1095 键规格",
    consequence="键连接实际承载能力与标准值不符，打滑或过盈",
    category="standards", name="键槽深度与标准不符",
    condition=lambda p: _keyway_std_mismatch(p),
    analysis="轴槽深度未按 GB/T 1095 与轴径匹配的键规格选取，键连接的实际承载能力"
             "与标准值不符，可能出现打滑或过盈。",
    risk="medium", level="warning", standard="GB/T 1095-2003（平键键槽尺寸）",
    recommendation="按轴径查表修正槽深/键宽（见 knowledge_base.gbt.KEYWAY_STD）。",
    applies_to=["shaft"],
))

register(Rule(
    id="sd_iso2768",
    cause="未注公差默认按 ISO 2768-mK（IT14 级）执行",
    consequence="高精度配合部位无法保证装配精度与互换性",
    category="standards", name="未注公差建议",
    condition=lambda p: True,
    analysis="图纸未标注公差时，加工尺寸默认按未注公差执行：线性尺寸 ISO 2768-mK 为 "
             "±0.1~±0.3mm（按尺寸段），形位公差 K 级。高精度配合部位应显式标注。",
    risk="low", level="info", standard="ISO 2768-1/-2（一般公差）",
    recommendation="轴承位、键槽等关键部位标注具体公差（k6/m6、键槽对称度 8 级），其余按 ISO 2768-mK。",
))




# ---------------------------------------------------------------- 材料选型

register(Rule(
    id="mt_steel45_temper",
    category="materials", name="45钢未指定热处理",
    condition=lambda p: "45" in str(p.get("material", ""))
                        and not any(k in str(p.get("material", "")) for k in ("调质", "正火", "淬火")),
    analysis="45钢供货态（热轧/正火）屈服强度约 275MPa，经调质处理（217~255HBW）后可达 "
             "355MPa 以上，且综合韧性与疲劳强度显著提升。轴类零件承载与耐磨性依赖热处理状态。",
    cause="材料仅标注牌号未指定热处理工艺，零件将按供货态执行，力学性能不达设计预期",
    consequence="轴类零件承载能力不足，表面耐磨性差，早期失效风险高",
    risk="medium", level="warning",
    standard="GB/T 699-2015（优质碳素结构钢）",
    recommendation="标注调质处理（HB 217~255），重要轴颈可增加高频淬火（HRC 45~50）。",
    applies_to=["shaft", "bolt", "gear"],
))

register(Rule(
    id="mt_aluminum_torque",
    category="materials", name="铝合金轴传递大扭矩",
    condition=lambda p: ("铝" in str(p.get("material", "")) or "Al" in str(p.get("material", "")))
                        and p.get("_torque_nm", 0) >= 200,
    analysis="6061-T6 铝合金许用扭转切应力约 [τ]≈40~55MPa，仅为调质钢的 1/2~2/3；"
             "传递 200Nm 以上扭矩时轴径需增大 25% 以上，且铝合金弹性模量低（E=69GPa），"
             "扭转变形量大。",
    cause="铝合金强度与刚度显著低于钢，大扭矩工况下截面尺寸与变形难以满足要求",
    consequence="轴径偏大导致整机重量优势丧失，扭角过大影响传动精度，疲劳寿命低",
    risk="medium", level="warning",
    standard="GB/T 3190（变形铝及铝合金牌号）",
    recommendation="大扭矩轴改用 45钢/40Cr，或增大轴径并校核扭转变形量；铝仅用于轻载结构件。",
    needs_torque=True,
))

register(Rule(
    id="mt_aluminum_state",
    category="materials", name="铝合金未注状态",
    condition=lambda p: ("铝" in str(p.get("material", "")) or "Al" in str(p.get("material", "")))
                        and not any(k in str(p.get("material", "")) for k in ("T6", "T5", "T4", "O", "F")),
    analysis="铝合金力学性能依赖热处理状态：6061-O 抗拉仅 125MPa，T6 时效后可达 310MPa。"
             "不标注状态时强度无法保证。",
    cause="铝合金牌号必须配合状态代码（如 6061-T6）才能确定力学性能",
    consequence="按供货态（F/O 态）验收时强度远低于设计值，结构失效风险",
    risk="low", level="info",
    standard="GB/T 3190 / GB/T 6892（状态代号）",
    recommendation="标注完整状态，如 6061-T6、7075-T6。",
    applies_to=["shaft", "flange", "gear"],
))

register(Rule(
    id="mt_stainless_machining",
    category="materials", name="不锈钢加工硬化风险",
    condition=lambda p: str(p.get("material", "")) in ("304", "316", "316L", "不锈钢", "SUS304"),
    analysis="奥氏体不锈钢加工硬化显著（硬化系数约钢的 2 倍）、导热系数低（约为碳钢 1/3）、"
             "切屑粘刀：攻丝、深孔、薄壁加工时刀具磨损快且易咬死。",
    cause="奥氏体组织在切削应力下发生形变诱发马氏体转变，刀具切刃处材料迅速硬化",
    consequence="攻丝/深孔加工废品率高，刀具成本上升，表面质量不稳定",
    risk="low", level="info",
    standard="GB/T 1220（不锈钢棒）",
    recommendation="采用硬质合金刀具 + 充足冷却；螺纹加工用挤压丝锥；避免深径比>5 的孔。",
    applies_to=["shaft", "flange", "gear", "bolt"],
))

register(Rule(
    id="mt_stainless_torque",
    category="materials", name="不锈钢轴强度校核提示",
    condition=lambda p: str(p.get("material", "")) in ("304", "316", "316L", "不锈钢", "SUS304")
                        and p.get("_torque_nm", 0) >= 100,
    analysis="304/316 不锈钢屈服强度约 205~240MPa（轧态），低于 45钢调质（355MPa）；"
             "相同扭矩下轴径需增大，且 304 无磁性要求时注意加工硬化。",
    cause="不锈钢屈服强度与抗扭能力低于调质碳钢",
    consequence="轴径不足时扭转变形超标，或需要显著加大截面导致成本上升",
    risk="low", level="info",
    standard="GB/T 1220",
    recommendation="重载轴优先 45钢/40Cr；不锈钢仅用于耐蚀场合并校核强度。",
    needs_torque=True,
))


# ---------------------------------------------------------------- 辅助函数

def _max_step_diff(p) -> float:
    segs = p.get("segments") or []
    ds = [float(s.get("d", 0)) for s in segs if s.get("d", 0) > 0]
    return max((max(ds) - min(ds), 0))


def _keyway(p) -> bool:
    kw = p.get("keyway") or {}
    return bool(kw.get("enabled"))


def _keyway_seg(p) -> dict:
    segs = p.get("segments") or []
    kw = p.get("keyway") or {}
    idx = int(kw.get("seg_index", 0) or 0)
    if 0 <= idx < len(segs):
        return segs[idx]
    return segs[0] if segs else {}


def _keyway_end_margin(p) -> float:
    kw = p.get("keyway") or {}
    seg = _keyway_seg(p)
    L = float(seg.get("L", 0) or 0)
    lk = float(kw.get("lk", 0) or 0)
    return (L - lk) / 2


def _torsion_fail(p) -> bool:
    """按 [τ] 校核：任一轴段不满足则触发。"""
    torque = p.get("_torque_nm")
    if not torque:
        return False
    material = str(p.get("material", "45钢"))
    tau_allow = {"40Cr": 55, "35CrMo": 60, "42CrMo": 60}.get(material, 40.0)
    segs = [s for s in (p.get("segments") or []) if s.get("d", 0) > 0]
    if not segs:
        return False
    return any(
        (16 * float(torque) * 1000) / (math.pi * float(s["d"]) ** 3) > tau_allow
        for s in segs
    )


def _std_keyway_t(d) -> float:
    for spec, (t, lo, hi) in gbt.KEYWAY_STD.items():
        if lo <= d < hi:
            return t
    return 5.0


def _keyway_std_mismatch(p) -> bool:
    if not _keyway(p):
        return False
    kw = p.get("keyway") or {}
    d = float(_keyway_seg(p).get("d", 0) or 0)
    t = float(kw.get("t", 0) or 0)
    for spec, (std_t, lo, hi) in gbt.KEYWAY_STD.items():
        if lo <= d < hi:
            return abs(std_t - t) > 0.3
    return False


def _gear_rim(p):
    m = float(p.get("m", 0) or 0)
    z = float(p.get("z", 0) or 0)
    x = float(p.get("x", 0) or 0)
    d_hub = float(p.get("d_hub", 0) or 0)
    if m <= 0 or z <= 0 or d_hub <= 0:
        return None
    df = m * z - 2.5 * m + 2 * m * x
    return (df - d_hub) / 2


def _slenderness(p) -> float:
    segs = [s for s in (p.get("segments") or []) if s.get("d", 0) > 0]
    if not segs:
        return 0
    total = sum(float(s.get("L", 0) or 0) for s in segs)
    dmax = max(float(s["d"]) for s in segs)
    return total / dmax if dmax else 0


def _short_segments(p) -> bool:
    segs = [s for s in (p.get("segments") or []) if s.get("d", 0) > 0 and s.get("L", 0) > 0]
    return any(float(s["L"]) < 2 * float(s["d"]) / 3 for s in segs)


def _bearing_shoulder_low(p) -> bool:
    """检测疑似轴承位（45/30/35/40/50mm 轴颈段）相邻轴肩高度是否过小。"""
    segs = [s for s in (p.get("segments") or []) if s.get("d", 0) > 0]
    for i, s in enumerate(segs):
        d = float(s["d"])
        if d not in (30, 35, 40, 45, 50, 55):
            continue
        neighbors = []
        if i > 0:
            neighbors.append(float(segs[i - 1]["d"]))
        if i < len(segs) - 1:
            neighbors.append(float(segs[i + 1]["d"]))
        for nd in neighbors:
            if nd > d:
                h = (nd - d) / 2
                if h < 0.035 * d:
                    return True
    return False


def _bearing_seat_short(p) -> bool:
    segs = [s for s in (p.get("segments") or []) if s.get("d", 0) > 0]
    for s in segs:
        d = float(s["d"])
        L = float(s.get("L", 0) or 0)
        if d in (30, 35, 40, 45, 50, 55) and 0 < L < 30:
            return True
    return False
