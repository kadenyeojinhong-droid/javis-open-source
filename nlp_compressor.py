"""nlp_compressor.py

Convert natural language requirements into structured ORDER.json using agy CLI
with schema validation and option extraction.
"""

import json
import os
import subprocess
import sys


def _strip_markdown_code_block(text: str) -> str:
    """Strip markdown code fence if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_order_dict(obj):
    """Recursively search for a dictionary containing the 'options' field."""
    if isinstance(obj, dict):
        if "options" in obj and isinstance(obj["options"], list):
            return obj
        # Check standard wrapper fields first
        for key in ("result", "response", "content", "output", "data"):
            if key in obj:
                val = obj[key]
                if isinstance(val, dict):
                    res = _extract_order_dict(val)
                    if res is not None:
                        return res
                elif isinstance(val, str):
                    cleaned = _strip_markdown_code_block(val)
                    try:
                        parsed = json.loads(cleaned)
                        res = _extract_order_dict(parsed)
                        if res is not None:
                            return res
                    except Exception:
                        pass
        # Check remaining dictionary values
        for val in obj.values():
            if isinstance(val, dict):
                res = _extract_order_dict(val)
                if res is not None:
                    return res
            elif isinstance(val, str):
                cleaned = _strip_markdown_code_block(val)
                try:
                    parsed = json.loads(cleaned)
                    res = _extract_order_dict(parsed)
                    if res is not None:
                        return res
                except Exception:
                    pass
    return None


def parse_agy_output(raw: str) -> dict:
    """Pure function to parse agy output and validate exactly 3 options.

    Compatible with direct JSON and nested string JSON (e.g. inside result/response).
    Raises ValueError if options is missing or does not contain exactly 3 items.
    """
    if not isinstance(raw, str):
        raise ValueError("raw output must be a string")

    cleaned = _strip_markdown_code_block(raw)
    try:
        parsed_data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON from output: {e}")

    order = _extract_order_dict(parsed_data)
    if not isinstance(order, dict) or "options" not in order:
        raise ValueError("Could not find order structure with 'options' in output")

    options = order.get("options")
    if not isinstance(options, list) or len(options) != 3:
        got = len(options) if isinstance(options, list) else "not a list"
        raise ValueError(f"Expected exactly 3 options, got {got}")

    return order


def compress(text: str) -> dict:
    """Call agy CLI to compress natural language text into structured order."""
    prompt = (
        f"You are an expert system architect. Analyze the user's requirement and generate "
        f"an execution order with exactly 3 implementation options: "
        f"Option A (极速轻量), Option B (稳健工程), Option C (零新依赖复用).\n\n"
        f"Requirement:\n{text}"
    )

    schema_path = os.path.join(os.path.dirname(__file__), "schemas", "order.schema.json")
    if not os.path.exists(schema_path):
        schema_path = "schemas/order.schema.json"

    cmd = [
        "agy",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--json-schema",
        schema_path,
        "--print-timeout",
        "120s",
    ]

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=True,
    )

    data = parse_agy_output(res.stdout)

    os.makedirs(".ai_bus", exist_ok=True)
    out_file = os.path.join(".ai_bus", "ORDER.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


def main():
    if len(sys.argv) < 2:
        print("Usage: python nlp_compressor.py \"<requirement>\"")
        sys.exit(1)
    user_input = sys.argv[1]
    result = compress(user_input)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
