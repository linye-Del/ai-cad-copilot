"""FreeCAD-side probe for native PartDesign operations.

This script is a supplementary API compatibility test.  It does not represent
the Live GUI acceptance test and is never used by the production executor.
"""

import json
import os
import sys
import traceback


def _args():
    return [arg for arg in sys.argv[1:]
            if arg != "--pass" and not arg.startswith("-c") and
            not arg.startswith("exec(open")]


def main():
    args = _args()
    if len(args) < 3:
        raise RuntimeError("Expected repo_dir, plan_json, result_json")
    repo_dir, plan_path, result_path = args[:3]
    sys.path.insert(0, os.path.join(repo_dir, "freecad_addon"))
    from AICADCopilot.operations.executor import LiveOperationExecutor

    with open(plan_path, encoding="utf-8") as handle:
        plan = json.load(handle)
    result = {"ok": False}
    try:
        execution = LiveOperationExecutor().execute_plan({"plan": plan})
        result = {"ok": True, "execution": execution}
    except Exception:
        result = {"ok": False, "error": traceback.format_exc()}
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
