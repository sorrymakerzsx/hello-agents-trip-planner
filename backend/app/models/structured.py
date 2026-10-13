"""Reliable extraction and validation of JSON returned by an LLM."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first balanced JSON object from plain text or Markdown."""
    if not isinstance(text, str):
        raise ValueError("model response must be text")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.IGNORECASE | re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start < 0:
        raise ValueError("model response does not contain a JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(candidate)):
        char = candidate[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(candidate[start:index + 1])
    raise ValueError("incomplete JSON object in model response")


def validate_model_response(text: str, model_type: type[T]) -> T:
    """Parse and validate an LLM response with a Pydantic model."""
    return model_type.model_validate(extract_json_object(text))
