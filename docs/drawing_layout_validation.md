# Drawing Layout Engine 验收记录

> 历史验收记录（2026-08-29），用于说明 `DrawingLayoutEngine` / `DrawingValidator` 的设计与
> 边界。当前发布重新运行了布局/规则单元测试；未重新执行本记录中的全部 GUI 压力测试。

## 结论

`SteppedShaft_300mm` 从同一 FreeCAD Document 重新生成 TechDraw，并且只有在自动布局验证
全部通过后才允许导出 PDF。

最终状态：`Drawing layout validated = PASS`

```json
{
  "inside_border": true,
  "standard_scale": true,
  "dimension_overlap": false,
  "view_overlap": false,
  "title_block_overlap": false,
  "required_dimensions_present": true,
  "associative_dimensions": true,
  "local_feature_callouts": true,
  "spurious_0_63": false
}
```

## 300 mm 当前模型回归

- 页面：A4 横向
- 标准比例：1:2
- 真实关联尺寸：7 个 `TechDraw::DrawViewDimension`
- 尺寸值：总长 300、中央段 150、对称端段 2×75、直径 Φ30、Φ40 h6、C1、R1.25
- 中心线与端视图中心标记：存在
- 材料、表面粗糙度、一般公差与标题栏：存在
- 异常 0.63：不存在
- R 引线：关联到实际二维投影圆角，局部引线长度门槛通过

当前模型没有键槽，因此没有伪造键槽宽度、深度或位置尺寸；若模型存在键槽但无法取得关联
几何，生成器会失败而不是用文字冒充尺寸。当前模型的最大实际直径为 Φ40，因此没有虚构 Φ50。

## 压力测试

| 模型 | 页面 | 自动比例 | 关联尺寸 | 越界/碰撞 | 结果 |
|---|---|---|---:|---|---|
| 150 mm 阶梯轴 | A4 横向 | 1:1 | 7 | 无 | PASS |
| 300 mm 阶梯轴 | A4 横向 | 1:2 | 7 | 无 | PASS |
| 500 mm 阶梯轴 | A4 横向 | 1:2.5 | 7 | 无 | PASS |

三组测试共用同一套页面、比例、投影视图、尺寸与碰撞算法，没有按长度写固定坐标分支。

## 关键修复

1. 建立独立 `DrawingLayoutEngine`，计算页面安全区、标准比例、视图、尺寸与注释位置。
2. 建立 `DrawingValidator`，以越界、比例、视图/尺寸/标题栏碰撞、必需尺寸和关联状态作为硬门槛。
3. 使用实际 TechDraw 投影包围盒进行一次 Observe → Correct，再创建尺寸。
4. 修复 FreeCAD 1.1 中尺寸位置相对于引用视图的坐标语义。
5. 将尺寸引用改为当前主视图的 `References2D`，并验证引用对象状态为 Up-to-date。
6. 修复旧页面删除后遗留孤立视图/尺寸的问题。
7. 通过实际几何值和二维位置选择圆角/倒角引用，消除错误的 0.63 与跨零件长引线。
8. 对等长端段采用 `2×L` 的非重复制造标注，同时仍引用真实投影几何。
9. PDF 导出前强制再次执行验证；任一硬门槛失败时拒绝报告成功。

## 回归命令

```powershell
python -m pytest tests\test_drawing_layout.py tests\test_live_agent.py -q
```

历史记录结果：`10 passed`。v0.2.0 的全量测试结果为 `52 passed`。

本次记录不修改 `start_ai_cad.bat`、`start_ai_cad.ps1`、Backend 生命周期、Live Bridge 或
一键启动流程。
