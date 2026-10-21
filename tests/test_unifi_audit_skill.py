"""The audit skill only names tools this repo registers.

``do_not_call`` must be the full set of mutating tools. A new write tool
fails this test until the skill's refuse list names it. A backticked name
that looks like a tool and is not registered fails it too.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "unifi-readonly-audit" / "SKILL.md"
SRC = ROOT / "src" / "mcp_unifi"

_AUDITED = re.compile(r"""@audited\(\s*["']([a-z0-9_]+)["']\s*,\s*mutates=(True|False)\s*\)""")
_BACKTICK = re.compile(r"`([a-z][a-z0-9_]*)`")
_TOOL_PREFIXES = (
    "list_",
    "get_",
    "audit_",
    "create_",
    "update_",
    "delete_",
    "set_",
    "toggle_",
    "block_",
    "unblock_",
    "restart_",
    "rename_",
    "locate_",
    "quarantine_",
    "provision_",
    "restore_",
    "confirm_",
    "trigger_",
)
_START = "<!-- tool-registry:start -->"
_END = "<!-- tool-registry:end -->"
# Response fields whose names share a tool prefix. Not tools.
_FIELD_NAMES = frozenset({"block_list", "update_available"})


def _registry() -> dict[str, bool]:
    found: dict[str, bool] = {}
    for path in SRC.rglob("*.py"):
        for name, flag in _AUDITED.findall(path.read_text(encoding="utf-8")):
            mutates = flag == "True"
            assert name not in found or found[name] is mutates, name
            found[name] = mutates
    assert found, "no @audited tools found"
    return found


def _skill_lists(text: str) -> dict[str, set[str]]:
    start = text.index(_START)
    end = text.index(_END)
    block = text[start:end]
    fence = block.split("```yaml", 1)[1].split("```", 1)[0]
    loaded = yaml.safe_load(fence)
    assert isinstance(loaded, dict)
    lists: dict[str, set[str]] = {}
    for key in ("call", "not_this_check", "do_not_call"):
        values = loaded[key]
        assert isinstance(values, list)
        names = set(values)
        assert len(names) == len(values), f"duplicate in {key}"
        assert all(isinstance(name, str) for name in names)
        lists[key] = names
    return lists


def test_audit_skill_tools_match_the_registry() -> None:
    text = SKILL.read_text(encoding="utf-8")
    registered = _registry()
    lists = _skill_lists(text)
    mutating = {name for name, mutates in registered.items() if mutates}
    reading = {name for name, mutates in registered.items() if not mutates}

    assert lists["do_not_call"] == mutating
    assert lists["call"] <= reading
    assert lists["not_this_check"] <= reading
    assert lists["call"].isdisjoint(lists["not_this_check"])
    assert lists["call"].isdisjoint(lists["do_not_call"])

    classified = lists["call"] | lists["not_this_check"] | lists["do_not_call"]
    for token in _BACKTICK.findall(text):
        looks_like_tool = token.startswith(_TOOL_PREFIXES)
        if token in _FIELD_NAMES:
            continue
        if token in registered or looks_like_tool:
            assert token in registered, f"skill names a tool that is not registered: {token}"
            assert token in classified, f"skill mentions {token} outside the tool registry"
