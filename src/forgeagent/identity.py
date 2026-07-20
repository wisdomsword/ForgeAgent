"""Runtime identity prompt composition."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from jinja2 import Environment, StrictUndefined

_PROMPTS_PACKAGE = "forgeagent.res.prompts"


@dataclass(frozen=True)
class IdentitySnapshot:
    """Raw identity content and digests used by later trust decisions."""

    soul: str | None
    user: str | None
    agents: str | None
    memory: str | None
    raw_content_digest: str
    effective_input_digest: str


@dataclass(frozen=True)
class ApprovedIdentity:
    """Identity content approved to reach the model."""

    soul: str | None
    user: str | None
    project_agents: str | None
    memory: str | None


def _read_prompt_resource(filename: str) -> str:
    return resources.files(_PROMPTS_PACKAGE).joinpath(filename).read_text(encoding="utf-8")


def compose_system_prompt(identity: ApprovedIdentity) -> str:
    """Render the bundled system prompt for an approved identity."""
    protocol = _read_prompt_resource("protocol.md")
    soul = identity.soul if identity.soul is not None else _read_prompt_resource("default_soul.md")
    template_source = _read_prompt_resource("system.j2")
    environment = Environment(
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    template = environment.from_string(template_source)
    return template.render(
        soul=soul,
        protocol=protocol,
        user=identity.user,
        project_agents=identity.project_agents,
        memory=identity.memory,
    )
