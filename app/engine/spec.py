"""The contract between the LLM (decompose step) and System 1 (docs/ai-design.md §6-8, ADR 0008).

Each model has two forms:
- a Pydantic model, which validates what the LLM returned (types, discriminated union, ops);
- a JSON schema sent to the API as the structured-output format. It is hand-written because
  structured outputs require `additionalProperties: false` on every object and don't support
  numeric constraints, so free-form maps (user facts) are arrays of {name, type, value}.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

FactType = Literal["number", "boolean", "string"]
Op = Literal[">=", ">", "<=", "<", "==", "!="]
EQUALITY_OPS: frozenset[str] = frozenset({"==", "!="})


class UserFact(BaseModel):
    name: str
    type: FactType
    value: float | bool | str


class FactCheck(BaseModel):
    id: str
    check: Literal["fact"]
    fact: str
    op: Op
    value: float | bool | str
    source_chunk: str
    label: str
    rule: str


class NliCheck(BaseModel):
    id: str
    check: Literal["nli"]
    hypothesis: str
    source_chunk: str
    label: str
    rule: str


Decision = Annotated[FactCheck | NliCheck, Field(discriminator="check")]


class DecisionPlan(BaseModel):
    user_facts: list[UserFact] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    combine: Literal["ALL", "ANY"] = "ALL"

    def facts(self) -> dict[str, UserFact]:
        return {f.name: f for f in self.user_facts}


class ComparisonPlan(BaseModel):
    options: list[str]
    criterion: str
    better: Literal["lower", "higher"]


class ExtractedValue(BaseModel):
    option: str
    value: float | None
    unit: str | None
    source_chunk: str | None


class ExtractedValues(BaseModel):
    values: list[ExtractedValue]


# --- JSON schemas for structured outputs --------------------------------------------------------

_SCALAR = {"anyOf": [{"type": "number"}, {"type": "boolean"}, {"type": "string"}]}


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_STR = {"type": "string"}

DECISION_PLAN_SCHEMA = _obj(
    {
        "user_facts": {
            "type": "array",
            "items": _obj(
                {
                    "name": _STR,
                    "type": {"type": "string", "enum": ["number", "boolean", "string"]},
                    "value": _SCALAR,
                }
            ),
        },
        "decisions": {
            "type": "array",
            "items": {
                "anyOf": [
                    _obj(
                        {
                            "id": _STR,
                            "check": {"type": "string", "enum": ["fact"]},
                            "fact": _STR,
                            "op": {"type": "string", "enum": [">=", ">", "<=", "<", "==", "!="]},
                            "value": _SCALAR,
                            "source_chunk": _STR,
                            "label": _STR,
                            "rule": _STR,
                        }
                    ),
                    _obj(
                        {
                            "id": _STR,
                            "check": {"type": "string", "enum": ["nli"]},
                            "hypothesis": _STR,
                            "source_chunk": _STR,
                            "label": _STR,
                            "rule": _STR,
                        }
                    ),
                ]
            },
        },
        "combine": {"type": "string", "enum": ["ALL", "ANY"]},
    }
)

COMPARISON_PLAN_SCHEMA = _obj(
    {
        "options": {"type": "array", "items": _STR},
        "criterion": _STR,
        "better": {"type": "string", "enum": ["lower", "higher"]},
    }
)

EXTRACTED_VALUES_SCHEMA = _obj(
    {
        "values": {
            "type": "array",
            "items": _obj(
                {
                    "option": _STR,
                    "value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "unit": {"anyOf": [_STR, {"type": "null"}]},
                    "source_chunk": {"anyOf": [_STR, {"type": "null"}]},
                }
            ),
        }
    }
)


# --- Gemini variant: no anyOf ------------------------------------------------------------------
# Gemini's structured output documents JSON Schema type arrays (["number", "null"]) but not
# clearly anyOf, so the Gemini client sends a flattened form of the same schemas:
# - anyOf of scalar types → one type array;
# - anyOf of objects (the fact | nli decision union) → one object: shared properties as they are,
#   branch-specific ones nullable (enums on them are dropped; Pydantic still checks them).
# The response is validated with the same Pydantic models, so the contract doesn't loosen.


def _as_types(schema: dict[str, Any]) -> list[str]:
    t = schema.get("type")
    return t if isinstance(t, list) else [t]


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in schema.items() if k != "enum"}
    types = _as_types(schema)
    out["type"] = [*types, "null"] if "null" not in types else types
    return out


def flatten_any_of(schema: Any) -> Any:
    if isinstance(schema, list):
        return [flatten_any_of(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    if "anyOf" in schema:
        branches = [flatten_any_of(b) for b in schema["anyOf"]]
        if all(b.get("type") != "object" and set(b) <= {"type"} for b in branches):
            types: list[str] = []
            for b in branches:
                types.extend(t for t in _as_types(b) if t not in types)
            return {"type": types}
        if all(b.get("type") == "object" for b in branches):
            names: list[str] = []
            for b in branches:
                names.extend(n for n in b["properties"] if n not in names)
            merged: dict[str, Any] = {}
            for name in names:
                found = [b["properties"][name] for b in branches if name in b["properties"]]
                if len(found) == len(branches) and all(f == found[0] for f in found):
                    merged[name] = found[0]
                elif len(found) == len(branches) and all("enum" in f for f in found):
                    merged[name] = {
                        "type": "string",
                        "enum": sorted({e for f in found for e in f["enum"]}),
                    }
                else:
                    merged[name] = _nullable(found[0])
            return {
                "type": "object",
                "properties": merged,
                "required": names,
                "additionalProperties": False,
            }
        raise ValueError("can't flatten a mixed anyOf")
    return {k: flatten_any_of(v) for k, v in schema.items()}
