"""Bounded, local-only JSON Schema validation for the gateway's text API."""

from __future__ import annotations

import json
import math
from fractions import Fraction
from typing import Any


class SchemaError(ValueError):
    pass


class InvalidOutput(ValueError):
    pass


class ValidationLimit(InvalidOutput):
    pass


def strict_json(text: str) -> Any:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON property")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Non-finite JSON number")

    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("Non-finite JSON number")
        return parsed

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float)


TYPES = {
    "null": lambda x: x is None,
    "boolean": lambda x: isinstance(x, bool),
    "string": lambda x: isinstance(x, str),
    "number": lambda x: type(x) is int or (type(x) is float and math.isfinite(x)),
    "integer": lambda x: type(x) is int or (type(x) is float and math.isfinite(x) and x == int(x)),
    "array": lambda x: isinstance(x, list),
    "object": lambda x: isinstance(x, dict),
}
ANNOTATIONS = {"title", "description", "default", "examples", "deprecated", "readOnly", "writeOnly", "$comment"}
KEYWORDS = ANNOTATIONS | {
    "$schema", "$ref", "$defs", "definitions", "type", "enum", "const", "properties", "required",
    "additionalProperties", "items", "prefixItems", "minItems", "maxItems", "uniqueItems",
    "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "minProperties", "maxProperties", "anyOf", "oneOf", "allOf", "not",
}


class Schema:
    """An explicit subset: unsupported assertions are refused, never ignored."""

    def __init__(self, root: Any):
        try:
            size = len(json.dumps(root, allow_nan=False).encode())
        except (ValueError, TypeError, RecursionError) as exc:
            raise SchemaError("Schema must be finite JSON") from exc
        if size > 32768:
            raise SchemaError("Schema exceeds 32768 bytes")
        self.root = root
        self.nodes = 0
        self.checked = set()
        self._check(root, 0)

    def _ref(self, ref: Any) -> Any:
        if not isinstance(ref, str) or not (ref == "#" or ref.startswith("#/")):
            raise SchemaError("Only local JSON Pointer references are supported")
        target = self.root
        try:
            for part in ref[2:].split("/") if ref != "#" else []:
                part = part.replace("~1", "/").replace("~0", "~")
                target = target[int(part)] if isinstance(target, list) else target[part]
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            raise SchemaError("Unresolved schema reference") from exc
        if not isinstance(target, (dict, bool)):
            raise SchemaError("Reference must identify a schema")
        return target

    def _check(self, node: Any, depth: int) -> None:
        self.nodes += 1
        if depth > 32 or self.nodes > 2048:
            raise SchemaError("Schema is too complex")
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            raise SchemaError("Schema must be an object or boolean")
        if id(node) in self.checked:
            return
        self.checked.add(id(node))
        if set(node) - KEYWORDS:
            raise SchemaError("Schema contains unsupported keywords")
        if "$schema" in node and node["$schema"] not in (
            "https://json-schema.org/draft/2020-12/schema",
            "https://json-schema.org/draft/2019-09/schema",
        ):
            raise SchemaError("Only the 2019-09/2020-12 schema dialects are supported")
        if "$ref" in node:
            self._check(self._ref(node["$ref"]), depth + 1)
        if "type" in node:
            types = node["type"] if isinstance(node["type"], list) else [node["type"]]
            if not types or any(not isinstance(t, str) or t not in TYPES for t in types):
                raise SchemaError("Invalid schema type")
        for key in ("$defs", "definitions", "properties"):
            if key in node:
                if not isinstance(node[key], dict):
                    raise SchemaError("Schema property map must be an object")
                for child in node[key].values():
                    self._check(child, depth + 1)
        if "required" in node:
            value = node["required"]
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                raise SchemaError("Required properties must be strings")
            if len(value) != len(set(value)):
                raise SchemaError("Required properties must be unique")
        for key in ("items", "additionalProperties", "not"):
            if key in node:
                self._check(node[key], depth + 1)
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            if key in node:
                if not isinstance(node[key], list) or not 1 <= len(node[key]) <= 32:
                    raise SchemaError("Schema branches must contain 1 to 32 schemas")
                for child in node[key]:
                    self._check(child, depth + 1)
        for key in ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"):
            if key in node and (type(node[key]) is not int or not 0 <= node[key] <= 1_000_000):
                raise SchemaError("Invalid schema size bound")
        for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"):
            if key in node and not TYPES["number"](node[key]):
                raise SchemaError("Invalid numeric schema bound")
        if "multipleOf" in node and node["multipleOf"] <= 0:
            raise SchemaError("multipleOf must be positive")
        if "uniqueItems" in node and type(node["uniqueItems"]) is not bool:
            raise SchemaError("uniqueItems must be boolean")
        if "enum" in node and (not isinstance(node["enum"], list) or not node["enum"]):
            raise SchemaError("enum must be a nonempty array")

    @staticmethod
    def _equal(a: Any, b: Any) -> bool:
        if type(a) in (int, float) and type(b) in (int, float):
            return a == b
        if type(a) is not type(b):
            return False
        if isinstance(a, list):
            return len(a) == len(b) and all(Schema._equal(x, y) for x, y in zip(a, b))
        if isinstance(a, dict):
            return a.keys() == b.keys() and all(Schema._equal(a[k], b[k]) for k in a)
        return a == b

    def validate(self, value: Any) -> None:
        budget = [50000]

        def visit(node, item, depth=0):
            budget[0] -= 1
            if depth > 64 or budget[0] < 0:
                raise ValidationLimit("JSON validation complexity limit exceeded")
            if node is True:
                return
            if node is False:
                raise InvalidOutput("Value is forbidden by schema")
            if "$ref" in node:
                visit(self._ref(node["$ref"]), item, depth + 1)
            types = node.get("type", [])
            types = [types] if isinstance(types, str) else types
            if types and not any(TYPES[t](item) for t in types):
                raise InvalidOutput("Value has the wrong JSON type")
            if "const" in node and not self._equal(item, node["const"]):
                raise InvalidOutput("Value does not match const")
            if "enum" in node and not any(self._equal(item, v) for v in node["enum"]):
                raise InvalidOutput("Value is not in enum")
            for key in ("anyOf", "oneOf", "allOf", "not"):
                if key not in node:
                    continue
                branches = [node[key]] if key == "not" else node[key]
                matches = 0
                for branch in branches:
                    try:
                        visit(branch, item, depth + 1)
                        matches += 1
                    except ValidationLimit:
                        raise
                    except InvalidOutput:
                        pass
                valid = {
                    "anyOf": matches > 0,
                    "oneOf": matches == 1,
                    "allOf": matches == len(branches),
                    "not": matches == 0,
                }[key]
                if not valid or budget[0] < 0:
                    raise InvalidOutput("Value does not satisfy schema branches")
            if isinstance(item, dict):
                if any(key not in item for key in node.get("required", [])):
                    raise InvalidOutput("Required property is missing")
                properties = node.get("properties", {})
                for key, child in item.items():
                    visit(properties.get(key, node.get("additionalProperties", True)), child, depth + 1)
                bounds(node, len(item), "minProperties", "maxProperties")
            elif isinstance(item, list):
                prefix = node.get("prefixItems", [])
                for index, child in enumerate(item):
                    visit(prefix[index] if index < len(prefix) else node.get("items", True), child, depth + 1)
                bounds(node, len(item), "minItems", "maxItems")
                if node.get("uniqueItems"):
                    seen = set()
                    for child in item:
                        encoded = json.dumps(child, sort_keys=True, separators=(",", ":"))
                        if encoded in seen:
                            raise InvalidOutput("Array items must be unique")
                        seen.add(encoded)
                    # JSON considers 1 and 1.0 equal; bool remains distinct.
                    if len(item) <= 256 and any(
                        self._equal(item[i], item[j]) for i in range(len(item)) for j in range(i)
                    ):
                        raise InvalidOutput("Array items must be unique")
                    if len(item) > 256:
                        raise ValidationLimit("uniqueItems validation is limited to 256 items")
            elif isinstance(item, str):
                bounds(node, len(item), "minLength", "maxLength")
            elif type(item) in (int, float):
                if not TYPES["number"](item):
                    raise InvalidOutput("Non-finite JSON number")
                bounds(node, item, "minimum", "maximum")
                if "exclusiveMinimum" in node and item <= node["exclusiveMinimum"]:
                    raise InvalidOutput("Number is below its exclusive minimum")
                if "exclusiveMaximum" in node and item >= node["exclusiveMaximum"]:
                    raise InvalidOutput("Number exceeds its exclusive maximum")
                if "multipleOf" in node and (Fraction(str(item)) / Fraction(str(node["multipleOf"]))).denominator != 1:
                    raise InvalidOutput("Number is not a multipleOf")

        def bounds(node, number, low, high):
            if low in node and number < node[low]:
                raise InvalidOutput("Value is below a schema bound")
            if high in node and number > node[high]:
                raise InvalidOutput("Value exceeds a schema bound")

        visit(self.root, value)
