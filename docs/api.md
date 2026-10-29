# API 参考

Base URL：`http://127.0.0.1:8000`

统一错误格式：

```json
{"detail": "错误描述", "code": "http_error"}
```

| 状态码 | 含义 |
|---|---|
| 400 | 请求/参数/规划/执行错误 |
| 404 | 会话或文件不存在 |
| 422 | Pydantic 参数校验失败 |
| 500 | FreeCAD 子进程或服务内部错误 |
| 503 | Live FreeCAD 未连接 |

> 当前 API 面向本机单用户，没有认证。不要暴露到公网。

## 1. 健康与 Live 状态

### GET `/api/health`

```json
{
  "ok": true,
  "service": "ai-cad-copilot",
  "pid": 12345,
  "freecad_cmd_compat": "C:\\...\\FreeCADCmd.exe",
  "execution_mode": "live_gui",
  "freecad_version": "1.1.3",
  "freecad_connected": true,
  "api_key": false,
  "output_dir": "E:\\...\\output"
}
```

`execution_mode`：

- `live_gui`：Add-on 已连接；
- `waiting_for_gui`：Backend 正常，但 FreeCAD 未连接。

### GET `/api/freecad/status`

```json
{
  "freecad_online": true,
  "status": "connected",
  "instance_id": "...",
  "freecad_version": "1.1.3",
  "active_document": "SteppedShaft_300mm",
  "active_object": "Fillet",
  "object_count": 23,
  "active_workbench": "AICADCopilotWorkbench",
  "workbench_registered": true,
  "dock_visible": true,
  "model_tree_visible": true,
  "active_modal": "",
  "last_event": {}
}
```

### GET `/api/freecad/events`

最近事件列表（用于调试/网页进度）。

### WS `/ws/freecad`

FreeCAD Add-on 专用。只接受 localhost；消息类型包括 `register`、`heartbeat`、
`command`、`response`、`event`、`user_query`。浏览器不应直接连接此端点。

## 2. Live Agent

### POST `/api/freecad/agent`

自然语言 → PartSpec → Design Engine → CadPlan → 当前 FreeCAD GUI。

**Body**

```json
{"query": "创建一个300mm阶梯轴"}
```

**支持的内置意图**

```text
创建一个300mm阶梯轴
创建一个M10螺栓
法兰 外径160 内径50 厚度18，8个M10螺栓孔，分度圆直径130
创建120×80×10mm带4个直径12mm孔的板
为当前模型生成工程图
```

**响应（简化）**

```json
{
  "ok": true,
  "message": "...",
  "part_spec": {
    "part_type": "shaft",
    "name": "SteppedShaft_300mm",
    "segments": [
      {"diameter_mm": 30, "length_mm": 75, "source": {"kind": "assumption"}}
    ],
    "assumptions": ["..."],
    "standards": ["GB/T 699"]
  },
  "cad_plan": {
    "plan_id": "...",
    "operations": [{"id": "1", "op": "create_document", "params": {}}]
  },
  "execution": {"completed": [], "failed": []},
  "inspection": {"issues": [], "passed": true},
  "report_path": "..."
}
```

`part_spec` 中每个尺寸的 `source.kind` 为：

- `user`：用户明确给出；
- `standard`：标准表派生；
- `design_engine`：设计规则计算；
- `assumption`：没有输入时的概念假设，必须复核。

### 其他 Live 操作

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/freecad/create-document` | 创建 Document，body `{"name": "..."}` |
| POST | `/api/freecad/create-box` | 原生 `Part::Box` 连接测试 |
| GET | `/api/freecad/document` | 当前 Document 信息 |
| GET | `/api/freecad/objects?all_properties=false` | 对象列表 |
| GET | `/api/freecad/objects/{name}` | 对象详情 |
| POST | `/api/freecad/objects` | 白名单对象创建 |
| PATCH | `/api/freecad/objects/{name}` | 白名单属性编辑 |
| DELETE | `/api/freecad/objects/{name}?force=false` | 删除对象 |
| POST | `/api/freecad/view` | `{"mode": "model"}` 或 `{"mode": "drawing"}` |
| POST | `/api/freecad/get-view` | 截图/视图参数 |
| POST | `/api/freecad/capture` | 保存 GUI 截图到指定路径 |
| POST | `/api/freecad/undo` | 撤销 |
| POST | `/api/freecad/redo` | 重做 |
| POST | `/api/freecad/reopen` | 重新打开 FCStd |

以上接口在 FreeCAD 未连接时返回 503。

## 3. Legacy 解析与会话

### POST `/api/parse`

Legacy 自然语言解析。无 Key 时回退规则引擎。

```json
{"text": "生成一个M10×40的六角头螺栓，8.8级"}
```

返回：

```json
{
  "ok": true,
  "spec": {
    "part_type": "bolt",
    "part_name": "M10x40六角头螺栓",
    "params": {"d": 10, "L": 40, "grade": "8.8"},
    "source": "rules"
  }
}
```

注意：Legacy 阶梯轴解析要求“直径×长度”的段信息；只给总长的“300mm 阶梯轴”属于
Live Agent 入口，不走 `/api/parse`。

### GET `/api/part-types`

返回 legacy 零件元数据：bolt / shaft / flange / gear，字段、示例、标准。

### 会话

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions` | 列出活跃会话 |
| GET | `/api/sessions/{id}` | 会话详情与 result.json |
| DELETE | `/api/sessions/{id}` | 关闭会话 |
| POST | `/api/sessions/{id}/parts` | FreeCADCmd 无头建模 |
| POST | `/api/sessions/{id}/drawing` | 重新生成 Legacy 工程图 |
| GET | `/api/sessions/{id}/files/{name}` | 下载产物 |

`parts` 请求：

```json
{
  "part_type": "shaft",
  "part_name": "demo_shaft",
  "params": {
    "segments": [{"d": 25, "L": 60}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
    "chamfer": 1.0,
    "fillet": 0.0,
    "material": "45钢"
  }
}
```

响应包含 `fcstd` / `step` / `stl` / `drawing` 文件路径。Legacy 建模耗时可能 5–30 秒。

## 4. 检查与报告

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/sessions/{id}/validate` | 27 条规则 + 公差检查；可选 `{"torque_nm": 500}` |
| POST | `/api/sessions/{id}/step-review` | STEP 特征、可制造性、设计检查 |
| POST | `/api/sessions/{id}/drawing-review` | DXF/SVG/PDF 图纸一致性；PDF 需可选 PyMuPDF |
| POST | `/api/sessions/{id}/review` | LLM 深度审查；需 API Key |
| POST | `/api/design/analyze` | 设计决策分析 |
| POST | `/api/demo/run` | Legacy 一键 Demo |
| GET | `/api/demo/report` | 下载 Demo 报告 |
| POST | `/api/chat` | Legacy LangChain Agent 对话 |

### validate 响应

```json
{
  "session_id": "...",
  "part_type": "shaft",
  "kind": "rule",
  "issues": [
    {
      "level": "warning",
      "problem": "键槽深度占比过大",
      "cause": "...",
      "consequence": "...",
      "recommendation": "...",
      "standard": "GB/T 1095-2003"
    }
  ],
  "passed": false,
  "report_path": "reports/....json"
}
```

`passed=false` 当且仅当存在 `error` 或 `warning`；`info` 不阻断。

### drawing-review 响应

```json
{
  "problems": [
    {"problem": "...", "location": "标注区", "risk": "medium", "suggestion": "..."}
  ],
  "passed": false,
  "ext": ".pdf",
  "texts_found": 12,
  "circles": 3
}
```

若未安装 `requirements-pdf.txt`，PDF 审查返回
`missing_optional_dependency`，不会伪造通过。
