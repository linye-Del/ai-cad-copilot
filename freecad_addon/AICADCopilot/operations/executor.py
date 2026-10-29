"""Live FreeCAD operation dispatcher and transactional CadPlan executor."""

import time

import FreeCAD as App
import FreeCADGui as Gui
import Part

from AICADCopilot.bridge.security import safe_name
from AICADCopilot.operations import body, document, export, feature, generic, sketch


class LiveOperationExecutor:
    def __init__(self, progress_callback=None):
        self.progress_callback = progress_callback or (lambda payload: None)
        self.context = {}
        self.dispatch = {
            "create_document": document.create_document,
            "create_body": body.create_body,
            "create_sketch": sketch.create_sketch,
            "add_geometry": sketch.add_geometry,
            "add_constraint": sketch.add_constraint,
            "set_constraint": sketch.set_constraint,
            "create_pad": feature.create_pad,
            "create_revolution": feature.create_revolution,
            "create_pocket": feature.create_pocket,
            "create_additive_helix": feature.create_additive_helix,
            "create_chamfer": feature.create_chamfer,
            "create_fillet": feature.create_fillet,
            "create_pattern": feature.create_linear_pattern,
            "create_hole": feature.create_hole,
            "remove_fillet": feature.remove_fillet_preserve_downstream,
            "save_document": export.save_document,
            "create_techdraw": export.create_techdraw,
            "validate_techdraw": export.validate_techdraw,
            "drawing_context": export.drawing_context,
            "export_techdraw_pdf": export.export_techdraw_pdf,
            "create_object": generic.create_object,
            "inspect_object": generic.inspect_object,
            "edit_object": generic.edit_object,
            "delete_object": generic.delete_object,
            "get_objects": generic.get_objects,
            "get_view": generic.get_view,
            "use_active_document": document.active_document,
        }

    def execute(self, action, params):
        if action == "execute_plan":
            return self.execute_plan(params)
        if action == "create_box":
            return self.create_box(params)
        if action == "inspect_document":
            return self.inspect_document()
        if action == "prepare_view":
            return document.prepare_view(params, self.context)
        if action == "capture_gui":
            return document.capture_gui(params, self.context)
        if action == "undo":
            return document.undo(params, self.context)
        if action == "redo":
            return document.redo(params, self.context)
        if action == "reopen_document":
            return document.reopen_document(params, self.context)
        if action == "use_active_document":
            return self._serialize(document.active_document(params, self.context))
        handler = self.dispatch.get(action)
        if handler is None:
            raise ValueError("Unsupported operation: %s" % action)
        result = handler(params, self.context)
        return self._serialize(result)

    def execute_plan(self, payload):
        plan = payload.get("plan") or payload
        operations = plan.get("operations") or []
        if not operations:
            raise ValueError("CadPlan has no operations")
        self.context = {}
        transaction_doc = App.ActiveDocument
        transaction_open = False
        created_document = None
        started = time.time()
        completed = []
        try:
            for index, operation in enumerate(operations):
                op = str(operation.get("op", ""))
                params = dict(operation.get("params") or {})
                for key in ("body", "profile", "sketch", "base", "source", "page", "path",
                            "name", "label", "length", "radius", "size", "selector", "geometry",
                            "constraints", "z_offset", "support_plane", "title", "material", "scale",
                            "angle", "axis", "pitch", "height"):
                    if key in operation and key not in params:
                        params[key] = operation[key]
                handler = self.dispatch.get(op)
                if handler is None:
                    raise ValueError("Unsupported CadPlan operation: %s" % op)
                result = handler(params, self.context)
                if op == "create_document":
                    created_document = result
                    transaction_doc = result
                if transaction_doc is None:
                    transaction_doc = self.context.get("document") or App.ActiveDocument
                if transaction_doc is not None and not transaction_open:
                    transaction_doc.openTransaction(str(plan.get("name") or "AI CAD Copilot Plan"))
                    transaction_open = True
                ref = str(operation.get("ref", "")).lstrip("$")
                if ref:
                    if isinstance(result, dict) and "page" in result:
                        self.context[ref] = result["page"]
                    elif not isinstance(result, dict):
                        self.context[ref] = result
                    else:
                        self.context[ref] = result
                if transaction_doc is not None:
                    transaction_doc.recompute()
                if hasattr(Gui, "updateGui"):
                    Gui.updateGui()
                item = {"index": index, "id": operation.get("id", ""), "op": op,
                        "ref": ref, "result": self._serialize(result)}
                completed.append(item)
                self.progress_callback({"event": "plan_progress", "plan_id": plan.get("plan_id", ""),
                                        "completed": index + 1, "total": len(operations), **item})
            if transaction_doc is not None and transaction_open:
                transaction_doc.commitTransaction()
            document.refresh_view()
            return {
                "plan_id": plan.get("plan_id", ""),
                "duration_s": round(time.time() - started, 2),
                "completed": completed,
                "document": transaction_doc.Name if transaction_doc else "",
                "tree": self.inspect_document(),
            }
        except Exception:
            if transaction_doc is not None and transaction_open:
                transaction_doc.abortTransaction()
                transaction_doc.recompute()
            if created_document is not None and not created_document.Objects:
                App.closeDocument(created_document.Name)
            raise

    def create_box(self, params):
        self.context = {}
        doc = App.ActiveDocument
        if doc is None:
            doc = document.create_document({"name": params.get("document", "AICADCopilot")},
                                           self.context)
        else:
            self.context["document"] = doc
        doc.openTransaction("AI CAD Copilot: Create Box")
        try:
            name = safe_name(params.get("name"), "AIBox")
            box = doc.addObject("Part::Box", name)
            box.Label = str(params.get("label") or "AI Test Box")[:128]
            box.Length = float(params.get("length", 50.0))
            box.Width = float(params.get("width", 30.0))
            box.Height = float(params.get("height", 20.0))
            doc.recompute()
            if box.Shape.isNull():
                raise RuntimeError("Part::Box shape is empty")
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        document.refresh_view()
        return {"document": doc.Name, "object": box.Name, "type_id": box.TypeId,
                "dimensions": {"length": float(box.Length), "width": float(box.Width),
                               "height": float(box.Height)}}

    def inspect_document(self):
        from AICADCopilot.bridge.serialization import serialize_document
        doc = App.ActiveDocument
        result = serialize_document(doc, all_properties=False)
        selection = Gui.Selection.getSelection() if hasattr(Gui, "Selection") else []
        result["active_object"] = selection[0].Name if selection else ""
        return result

    def _serialize(self, result):
        if result is None:
            return None
        if isinstance(result, dict):
            return {key: self._serialize(value) for key, value in result.items()}
        if isinstance(result, (list, tuple)):
            return [self._serialize(value) for value in result]
        if isinstance(result, (str, int, float, bool)):
            return result
        if hasattr(result, "TypeId"):
            return {"name": result.Name, "label": result.Label, "type_id": result.TypeId}
        return str(result)
