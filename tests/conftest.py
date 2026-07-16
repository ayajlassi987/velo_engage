"""Shared pytest setup. Path resolution for ml/ and each service's src/ is
handled by `[tool.pytest.ini_options] pythonpath` in the root pyproject.toml
(mirrors the sys.path shims already used at runtime, e.g.
ve_orchestrator/activities.py:22-28) — nothing infra-dependent belongs here.
"""
