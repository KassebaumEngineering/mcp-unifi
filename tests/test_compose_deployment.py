"""The standalone compose deployment stays read-only and unexposed.

The HTTP file hardcodes ``MCP_UNIFI_READONLY`` and binds ``MCP_HOST`` to
``BIND_ADDR`` with no default. A published port with no address would listen
on every host interface, so the file must not have a ``ports`` key either.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_DIR = ROOT / "deploy" / "compose"
HTTP_COMPOSE = COMPOSE_DIR / "docker-compose.yml"
STDIO_COMPOSE = COMPOSE_DIR / "docker-compose.stdio.yml"
CONTROLLERS = COMPOSE_DIR / "controllers.example.yaml"
HELM_VALUES = ROOT / "charts" / "mcp-unifi" / "values.yaml"

_READONLY_LINE = re.compile(r'(?m)^[ ]+MCP_UNIFI_READONLY:[ ]+"true"[ ]*$')
_ENTRYPOINT_ASSIGNMENT = "os.environ['MCP_UNIFI_READONLY'] = 'true'"
_SECRET_ENV = {
    "UNIFI_API_KEY",
    "UNIFI_ACCESS_API_KEY",
    "UNIFI_OS_PASSWORD",
    "MCP_UNIFI_AUTH_TOKENS",
}


def _load(path: Path) -> tuple[str, dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict)
    return text, loaded


def _service(doc: dict[str, object]) -> dict[str, object]:
    services = doc["services"]
    assert isinstance(services, dict)
    service = services["mcp-unifi"]
    assert isinstance(service, dict)
    return service


def _environment(service: dict[str, object]) -> dict[str, object]:
    env = service["environment"]
    assert isinstance(env, dict)
    return env


def test_http_compose_is_readonly_and_has_no_wildcard_bind() -> None:
    text, doc = _load(HTTP_COMPOSE)
    assert "0.0.0.0" not in text
    assert _READONLY_LINE.search(text)

    service = _service(doc)
    env = _environment(service)
    assert env["MCP_UNIFI_READONLY"] == "true"
    assert "$" not in str(env["MCP_UNIFI_READONLY"])

    host = env["MCP_HOST"]
    assert isinstance(host, str)
    assert "${BIND_ADDR:?" in host
    assert ":-" not in host
    assert "0.0.0.0" not in host

    assert service["network_mode"] == "host"
    assert "ports" not in service
    assert "env_file" not in service
    assert _SECRET_ENV.isdisjoint(env)
    assert env["MCP_UNIFI_AUTH_TOKEN_FILE"] == "/run/secrets/mcp_unifi_token"
    assert "MCP_UNIFI_AUTH_TOKENS" not in env

    entrypoint = service["entrypoint"]
    assert isinstance(entrypoint, list)
    assert _ENTRYPOINT_ASSIGNMENT in "\n".join(str(part) for part in entrypoint)

    assert service["read_only"] is True
    assert service["user"] == "1000:1000"
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["restart"] == "unless-stopped"
    assert service["mem_limit"] == "512m"
    deploy = service["deploy"]
    assert isinstance(deploy, dict)
    resources = deploy["resources"]
    assert isinstance(resources, dict)
    limits = resources["limits"]
    assert isinstance(limits, dict)
    assert limits["memory"] == "512M"

    volumes = service["volumes"]
    assert isinstance(volumes, list)
    controllers = next(
        item
        for item in volumes
        if isinstance(item, dict) and item.get("target") == "/etc/mcp-unifi/controllers.yaml"
    )
    assert controllers["read_only"] is True
    assert controllers["source"] == "./controllers.yaml"
    bind = controllers["bind"]
    assert isinstance(bind, dict)
    assert bind["create_host_path"] is False
    assert "./pins:/etc/mcp-unifi/pins:ro" in volumes
    assert "audit-log:/var/lib/mcp-unifi" in volumes
    assert env["MCP_UNIFI_AUDIT_PATH"] == "/var/lib/mcp-unifi/audit.jsonl"
    named = doc["volumes"]
    assert isinstance(named, dict)
    audit = named["audit-log"]
    assert isinstance(audit, dict)
    assert audit["name"] == "mcp-unifi-audit-log"


def test_stdio_compose_is_readonly_and_does_not_listen() -> None:
    text, doc = _load(STDIO_COMPOSE)
    assert "0.0.0.0" not in text
    assert "BIND_ADDR" not in text
    assert _READONLY_LINE.search(text)

    service = _service(doc)
    env = _environment(service)
    assert env["MCP_TRANSPORT"] == "stdio"
    assert env["MCP_UNIFI_READONLY"] == "true"
    assert "MCP_HOST" not in env
    assert "ports" not in service
    assert "env_file" not in service
    assert _SECRET_ENV.isdisjoint(env)
    assert "MCP_UNIFI_AUTH_TOKENS" not in env
    assert "MCP_UNIFI_AUTH_TOKEN_FILE" not in env

    entrypoint = service["entrypoint"]
    assert isinstance(entrypoint, list)
    assert _ENTRYPOINT_ASSIGNMENT in "\n".join(str(part) for part in entrypoint)

    assert service["read_only"] is True
    assert service["user"] == "1000:1000"
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["restart"] == "no"
    assert service["network_mode"] == "host"
    volumes = service["volumes"]
    assert isinstance(volumes, list)
    controllers = next(
        item
        for item in volumes
        if isinstance(item, dict) and item.get("target") == "/etc/mcp-unifi/controllers.yaml"
    )
    assert controllers["read_only"] is True
    bind = controllers["bind"]
    assert isinstance(bind, dict)
    assert bind["create_host_path"] is False
    named = doc["volumes"]
    assert isinstance(named, dict)
    audit = named["audit-log"]
    assert isinstance(audit, dict)
    assert audit["name"] == "mcp-unifi-audit-log"
    healthcheck = service["healthcheck"]
    assert isinstance(healthcheck, dict)
    assert healthcheck["disable"] is True


def test_compose_secrets_are_files() -> None:
    _, http_doc = _load(HTTP_COMPOSE)
    _, stdio_doc = _load(STDIO_COMPOSE)
    for doc in (http_doc, stdio_doc):
        secrets = doc["secrets"]
        assert isinstance(secrets, dict)
        assert secrets
        for spec in secrets.values():
            assert isinstance(spec, dict)
            file_path = spec["file"]
            assert isinstance(file_path, str)
            assert file_path.startswith("./secrets/")
            assert not file_path.endswith("README")


def test_controller_example_verifies_tls_and_pins() -> None:
    loaded = yaml.safe_load(CONTROLLERS.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    controllers = loaded["controllers"]
    assert isinstance(controllers, list)
    assert len(controllers) >= 2
    names: set[str] = set()
    for controller in controllers:
        assert isinstance(controller, dict)
        assert controller["verify_ssl"] is True
        assert isinstance(controller["pinned_cert"], str)
        assert controller["pinned_cert"].startswith("/etc/mcp-unifi/pins/")
        api_key_file = controller["api_key_file"]
        assert isinstance(api_key_file, str)
        assert api_key_file.startswith("/run/secrets/")
        assert "api_key" not in controller
        assert "os_password" not in controller
        names.add(str(controller["name"]))
    assert names == {"home", "cabin"}


def test_helm_readonly_defaults_true() -> None:
    """The chart sets MCP_UNIFI_READONLY explicitly, so a false default wins
    over the image. The chart default has to be true.
    """
    loaded = yaml.safe_load(HELM_VALUES.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    assert loaded["readOnly"] is True
