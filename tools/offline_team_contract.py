"""Structured output shapes; scientific validation stays in the team generator."""


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def schemas():
    role = object_schema({"id": {"type": "string", "enum": [f"role-{i}" for i in range(1, 7)]},
        "label": {"type": "string"}, "required": {"type": "boolean"}, "quote": {"type": "string"}})
    edge = object_schema({"role_id": {"type": "string"}, "claim_id": {"type": "string"},
        "coverage": {"type": "string", "enum": ["direct", "method_transfer", "adjacent"]},
        "reason": {"type": "string"}})
    edges = {"type": "array", "items": edge, "maxItems": 24}
    return {
        "decomposition": object_schema({"specific": {"type": "boolean"}, "objective": {"type": "string"},
                                       "roles": {"type": "array", "items": role, "maxItems": 6}}),
        "adjudication": object_schema({"edges": edges}),
        "verification": object_schema({"suitable_for_team": {"type": "boolean"}, "edges": edges}),
        "preflight": object_schema({"ready": {"type": "boolean"}}),
        "cov4": object_schema({"owned": {"type": "string", "enum": ["yes", "no", "unresolved"]},
                               "fundable": {"type": "string", "enum": ["yes", "no"]}, "reason": {"type": "string"}}),
    }
