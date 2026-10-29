"""PartDesign Body operations."""

from AICADCopilot.bridge.security import safe_name
from AICADCopilot.operations.document import current_document


def create_body(params, context):
    doc = current_document(context)
    name = safe_name(params.get("name"), "Body")
    body = doc.addObject("PartDesign::Body", name)
    body.Label = str(params.get("label") or name)[:128]
    context["body"] = body
    doc.recompute()
    return body
