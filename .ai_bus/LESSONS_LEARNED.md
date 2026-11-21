# Lessons learned

- Keep FastAPI route tests isolated by patching both the bus directory and the server root when routes use different path sources.
- Monkeypatch `subprocess.run` in tests so worker execution cannot invoke agent CLIs.
- Preserve the first configuration backup; repeated sync runs must not replace the original `.bak` snapshot.
- Antigravity headless mode prohibits shell commands; keep its work to file-reading and file-writing tasks.
