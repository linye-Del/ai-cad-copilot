# AI CAD Copilot FreeCAD Add-on

This Add-on connects the running FreeCAD GUI process to the AI CAD Copilot
backend. It is independent from the existing `FreeCADCmd` file-generation
pipeline.

## Install on Windows

1. Close FreeCAD.
2. Copy the `AICADCopilot` directory into:

   `%APPDATA%\FreeCAD\Mod\AICADCopilot`

3. Start the backend:

   `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`

4. Start FreeCAD. The Add-on connects automatically. The Report view prints
   `AI CAD Copilot: backend connected` when the connection succeeds.

The default gateway URL is `ws://127.0.0.1:8000/ws/freecad`. The Add-on accepts
only `ws://` loopback hosts (`127.0.0.1`, `localhost`, `::1`) and a typed command
allowlist; it never evaluates Python received from the Backend. Override the port
or loopback spelling with `AICAD_BACKEND_WS` when required.

## Smoke test

Open the web UI and wait for `FreeCAD Connected`, then click `Create Test Box`.
A native `Part::Box` named `AIBox` appears in the active FreeCAD document.

## Live modelling

Use either the Dock input or the web UI:

- `创建一个300mm阶梯轴`
- `创建一个M10螺栓`（原生 `PartDesign::AdditiveHelix` 螺纹）

The first command creates a native `PartDesign::Body` with three constrained
Sketches, three Pads, Chamfer and Fillet, then creates TechDraw views from the
final feature in the same Document. The whole CadPlan is one FreeCAD transaction,
so it can be undone and redone from the GUI.
