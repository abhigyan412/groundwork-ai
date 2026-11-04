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
