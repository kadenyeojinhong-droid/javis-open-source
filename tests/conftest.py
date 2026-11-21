import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm
import wt


@pytest.fixture(autouse=True)
def _no_real_worktrees(request, tmp_path, monkeypatch):
    """Tests must never create worktrees next to the real repo; test_wt.py uses its own temp repo."""
    # no test may reach the real CLIProxyAPI / Ollama; tests that need a reply patch llm.chat themselves
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("offline in tests")))
    if request.module.__name__.endswith("test_wt"):
        return
    monkeypatch.setattr(wt, "create", lambda agent, task_id: tmp_path)
    monkeypatch.setattr(wt, "diff", lambda task_id: "")
    monkeypatch.setattr(wt, "status", lambda: [])
