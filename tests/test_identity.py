"""Tests for runtime identity prompt composition."""

from __future__ import annotations

import itertools

import pytest

from forgeagent.identity import ApprovedIdentity, compose_system_prompt


def _labelled_combinations() -> list[tuple[str | None, str | None, str | None, str | None]]:
    markers = {
        "soul": "SOUL-MARKER",
        "user": "USER-MARKER",
        "project_agents": "AGENTS-MARKER",
        "memory": "MEMORY-MARKER",
    }
    return [
        tuple(
            markers[name] if present else None for name, present in zip(markers, flags, strict=True)
        )
        for flags in itertools.product([False, True], repeat=4)
    ]


@pytest.mark.parametrize("soul,user,project_agents,memory", _labelled_combinations())
def test_compose_system_prompt_combination_matrix(soul, user, project_agents, memory):
    identity = ApprovedIdentity(
        soul=soul,
        user=user,
        project_agents=project_agents,
        memory=memory,
    )
    rendered = compose_system_prompt(identity)

    assert "This conversation is driven by ForgeAgent" in rendered
    if soul is not None:
        assert soul in rendered
        assert "No custom Agent Identity (SOUL)" not in rendered
    else:
        assert "No custom Agent Identity (SOUL)" in rendered
    for value, heading in (
        (user, "## User Context"),
        (project_agents, "## Approved Project Instructions"),
        (memory, "## Project Memory"),
    ):
        if value is not None:
            assert heading in rendered
            assert value in rendered
        else:
            assert heading not in rendered


def test_compose_system_prompt_section_order():
    identity = ApprovedIdentity(
        soul="SOUL-MARKER",
        user="USER-MARKER",
        project_agents="AGENTS-MARKER",
        memory="MEMORY-MARKER",
    )
    rendered = compose_system_prompt(identity)
    assert (
        rendered.index("SOUL-MARKER")
        < rendered.index("This conversation is driven by ForgeAgent")
        < rendered.index("USER-MARKER")
        < rendered.index("AGENTS-MARKER")
        < rendered.index("MEMORY-MARKER")
    )


def test_compose_system_prompt_protocol_is_fixed_text():
    baseline = compose_system_prompt(ApprovedIdentity(None, None, None, None))
    with_identity = compose_system_prompt(ApprovedIdentity("X", "Y", "Z", "W"))
    assert baseline.count("Exec") == with_identity.count("Exec")
