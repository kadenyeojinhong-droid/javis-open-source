"""tests/test_t1.py

Unit tests for T1: repo_mapper and nlp_compressor.
"""

import json
import os
import pytest

import repo_mapper
from nlp_compressor import parse_agy_output


# --- Tests for repo_mapper ---

def test_repo_mapper_lists_own_functions(tmp_path):
    """repo_mapper should list its own functions and signatures."""
    # 1. Direct file signature check
    signatures = repo_mapper.parse_file_signatures("repo_mapper.py")
    sig_text = "\n".join(signatures)
    assert "def generate_repo_map(" in sig_text
    assert "def find_python_files(" in sig_text
    assert "def parse_file_signatures(" in sig_text
    assert "def main(" in sig_text

    # 2. End-to-end generate_repo_map check
    out_file = tmp_path / "REPO_MAP.txt"
    content = repo_mapper.generate_repo_map(root_dir=".", output_file=str(out_file))

    assert "repo_mapper.py" in content
    assert "def generate_repo_map(" in content
    assert "def find_python_files(" in content

    saved_content = out_file.read_text(encoding="utf-8")
    assert "repo_mapper.py" in saved_content
    assert "def generate_repo_map(" in saved_content


# --- Tests for nlp_compressor.parse_agy_output ---

@pytest.fixture
def valid_order_data():
    return {
        "goal": "Build HUD Server with WebSocket and Breaker",
        "constraints": ["No external database", "Port 8765"],
        "files": ["hud_server.py", "mcp_bridge.py"],
        "options": [
            {
                "id": "A",
                "title": "极速轻量",
                "summary": "Minimal monolithic server implementation",
                "modules": ["hud_server"],
            },
            {
                "id": "B",
                "title": "稳健工程",
                "summary": "Modular architecture with audit and state manager",
                "modules": ["hud_server", "state_manager", "audit_logger"],
            },
            {
                "id": "C",
                "title": "零新依赖复用",
                "summary": "Pure Python stdlib http.server implementation",
                "modules": ["http.server", "urllib"],
            },
        ],
    }


def test_parse_agy_output_direct_json(valid_order_data):
    """parse_agy_output should parse direct JSON string and extract 3 options."""
    raw_json = json.dumps(valid_order_data)
    result = parse_agy_output(raw_json)

    assert isinstance(result, dict)
    assert result["goal"] == valid_order_data["goal"]
    assert len(result["options"]) == 3
    assert [opt["id"] for opt in result["options"]] == ["A", "B", "C"]


def test_parse_agy_output_nested_string_json(valid_order_data):
    """parse_agy_output should handle JSON string nested in result/response fields."""
    order_json_str = json.dumps(valid_order_data)

    # 1. Nested in "result" field as string
    nested_result = json.dumps({"result": order_json_str, "status": "success"})
    res1 = parse_agy_output(nested_result)
    assert len(res1["options"]) == 3
    assert [opt["id"] for opt in res1["options"]] == ["A", "B", "C"]

    # 2. Nested in "response" field with markdown code block
    nested_response = json.dumps({
        "response": f"```json\n{order_json_str}\n```"
    })
    res2 = parse_agy_output(nested_response)
    assert len(res2["options"]) == 3
    assert res2["goal"] == valid_order_data["goal"]

    # 3. Nested in "output" field as string
    nested_output = json.dumps({"output": order_json_str})
    res3 = parse_agy_output(nested_output)
    assert len(res3["options"]) == 3


def test_parse_agy_output_options_not_three_raises_value_error(valid_order_data):
    """parse_agy_output should raise ValueError when options count is not 3."""
    # 2 options
    bad_2 = dict(valid_order_data)
    bad_2["options"] = valid_order_data["options"][:2]
    with pytest.raises(ValueError, match="Expected exactly 3 options"):
        parse_agy_output(json.dumps(bad_2))

    # 4 options
    bad_4 = dict(valid_order_data)
    extra_opt = {
        "id": "D",
        "title": "Extra Option",
        "summary": "Extra summary",
        "modules": [],
    }
    bad_4["options"] = valid_order_data["options"] + [extra_opt]
    with pytest.raises(ValueError, match="Expected exactly 3 options"):
        parse_agy_output(json.dumps(bad_4))

    # 0 options
    bad_0 = dict(valid_order_data)
    bad_0["options"] = []
    with pytest.raises(ValueError, match="Expected exactly 3 options"):
        parse_agy_output(json.dumps(bad_0))

    # Missing options field
    bad_missing = {
        "goal": "Test",
        "constraints": [],
        "files": [],
    }
    with pytest.raises(ValueError):
        parse_agy_output(json.dumps(bad_missing))

    # Invalid JSON
    with pytest.raises(ValueError):
        parse_agy_output("not valid json at all")
