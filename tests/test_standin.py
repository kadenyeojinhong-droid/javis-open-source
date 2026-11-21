import subprocess

import llm
import standin


def test_default_is_no_standin_and_down_expires(tmp_path):
    assert standin.active(tmp_path) == {}  # capsule starts with the three normal agents
    standin.mark_down("codex", "quota", hours=1, root=tmp_path)
    assert standin.is_down("codex", tmp_path) and not standin.is_down("agy", tmp_path)
    standin.mark_down("agy", "quota", hours=-1, root=tmp_path)  # already expired: slot goes back to agy
    assert list(standin.active(tmp_path)) == ["codex"]
    standin.mark_up("codex", tmp_path)
    assert standin.active(tmp_path) == {}


def test_exhausted_detection():
    assert standin.exhausted("You've hit your usage limit. Try again later.")
    assert standin.exhausted("HTTP 429 Too Many Requests")
    assert not standin.exhausted("SyntaxError: invalid syntax")


def test_implement_applies_model_diff_and_falls_through_chain(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    diff = "```diff\ndiff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n```"
    tried = []

    def chat(model, messages, **kwargs):
        tried.append(model)
        if model == "deepseek-v4-flash":
            raise llm.LLMUnavailable("402")
        return diff

    monkeypatch.setattr(llm, "chat", chat)
    rc, out, err = standin.implement(tmp_path, "set x to 2", ["a.py"], root=tmp_path)
    assert rc == 0, err
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\n"
    assert tried == ["deepseek-v4-flash", "gemma-4-26b-free"]


def test_implement_reports_when_all_models_down(tmp_path):
    rc, out, err = standin.implement(tmp_path, "anything", root=tmp_path)  # conftest keeps llm offline
    assert rc == 1 and "unavailable" in err


def test_exhausted_ignores_ordinary_errors():
    assert not standin.exhausted("RecursionError: maximum recursion depth exceeded")
    assert not standin.exhausted("credit card field missing in form")
    assert standin.exhausted("Error: insufficient credits")


def test_implement_rejects_unsafe_diff_and_hides_secrets(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".env").write_text("KEY=supersecret\n", encoding="utf-8")
    sent = []

    def chat(model, messages, **kwargs):
        sent.append(messages[-1]["content"])
        return "diff --git a/.git/hooks/pre-commit b/.git/hooks/pre-commit\n--- a/.git/hooks/pre-commit\n+++ b/.git/hooks/pre-commit\n@@ -0,0 +1 @@\n+evil\n"

    monkeypatch.setattr(llm, "chat", chat)
    rc, out, err = standin.implement(tmp_path, "x", [".env", "../outside.py"], root=tmp_path)
    assert rc == 1 and "rejected" in err
    assert "supersecret" not in sent[0]


def test_file_blocks_written_and_protected_paths_rejected(tmp_path):
    ok, detail = standin._apply(tmp_path, "<<<FILE pkg/a.py>>>\nx = 2\n<<<END>>>")
    assert ok and (tmp_path / "pkg" / "a.py").read_text(encoding="utf-8") == "x = 2\n"
    for bad in (".git/hooks/pre-commit", "../escape.py", ".ai_bus/settings.json"):
        ok, detail = standin._apply(tmp_path, f"<<<FILE {bad}>>>\nevil\n<<<END>>>")
        assert not ok and "rejected" in detail
    assert not (tmp_path.parent / "escape.py").exists()
