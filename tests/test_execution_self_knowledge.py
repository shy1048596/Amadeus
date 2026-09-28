"""Tests for Host-owned execution self-knowledge helpers."""

from agent_host.provider_contract import (
    ProviderCapabilities,
    ProviderManifest,
    ProviderRequirements,
)
from server.execution_self_knowledge import (
    build_capability_brief,
    build_delegate_guides,
    build_delegate_runtime_snapshot,
    build_execution_context,
    build_provider_readiness,
    build_task_health,
    enrich_rejection_receipt,
    recovery_hints_for_reason,
    render_execution_context_block,
)
from agent_host.provider_runtime import ProviderRuntime


def test_recovery_hints_for_provider_mismatch():
    hints = recovery_hints_for_reason(
        "planned_work_active_provider_mismatch",
        context={
            "current_work": {"provider": "pi"},
            "planned_provider": "codex",
        },
    )
    assert hints["category"] == "provider_continuity"
    assert hints["current_provider"] == "pi"
    assert hints["planned_provider"] == "codex"
    assert hints["recommended_actions_ja"]


def test_recovery_hints_unknown_reason_is_empty():
    assert recovery_hints_for_reason("totally_unknown_reason") == {}


def test_enrich_rejection_receipt_attaches_recovery():
    receipt = enrich_rejection_receipt(
        {"state": "rejected", "reason": "provider_unavailable"},
        context={"planned_provider": "missing"},
    )
    assert receipt["recovery"]["category"] == "provider_availability"
    assert receipt["recovery"]["planned_provider"] == "missing"


def test_build_capability_brief_from_requirements():
    requirements = {
        "codex": ProviderRequirements(workspace_access="write"),
        "pi": ProviderRequirements(workspace_access="read"),
    }
    manifests = {
        "codex": ProviderManifest(
            provider_id="codex",
            display_name="Codex",
            capabilities=ProviderCapabilities(workspace_access="write", interaction="bidirectional"),
        ),
        "pi": None,
    }
    brief = build_capability_brief(context_requirements=requirements, manifests=manifests)
    assert len(brief["providers"]) == 2
    codex = next(row for row in brief["providers"] if row["provider"] == "codex")
    pi = next(row for row in brief["providers"] if row["provider"] == "pi")
    assert codex["registered"] is True
    assert pi["registered"] is False
    assert brief["rules_ja"]


def test_build_task_health_permission_scope_missing():
    health = build_task_health(
        current_work={
            "work_item_id": "wi-1",
            "provider": "pi",
            "execution_status": "running",
            "attention": "permission",
        },
        pending_permissions=[{"reason": "tool execute", "scope": []}],
    )
    assert "permission_scope_missing" in health["blocked_by"]
    assert health["pending_permission_count"] == 1
    assert health["recommended_actions_ja"]


def test_build_execution_context_and_render_block():
    context = build_execution_context(
        context_requirements={"codex": ProviderRequirements(), "pi": ProviderRequirements()},
        current_work={"work_item_id": "wi-1", "provider": "codex", "execution_status": "running"},
    )
    rendered = render_execution_context_block(context)
    assert "[execution_context Host事実]" in rendered
    assert "capability_brief" in rendered
    assert "task_health" in rendered
    assert "delegate_guides" in rendered
    assert "codex" in context["delegate_guides"]
    assert "pi" in context["delegate_guides"]


def test_delegate_guides_include_operational_model():
    guides = build_delegate_guides(
        context_requirements={"pi": ProviderRequirements(), "codex": ProviderRequirements()},
    )
    assert "permission_model_ja" in guides["pi"]
    assert "owner_duties_ja" in guides["codex"]


def test_delegate_runtime_snapshot_bounds_activity():
    rows = build_delegate_runtime_snapshot([
        {
            "work_item_id": "wi-1",
            "provider": "pi",
            "relation": "running",
            "execution": "running",
            "activity_semantic_summary": "scanning files",
            "activity_last_tool": "execute_tool",
            "last_error": "permission denied",
        },
    ])
    assert rows[0]["provider"] == "pi"
    assert rows[0]["activity_semantic_summary"] == "scanning files"
    assert rows[0]["last_error"] == "permission denied"


def test_provider_readiness_from_runtime():
    runtime = ProviderRuntime()
    rows = build_provider_readiness(runtime=runtime, provider_ids=("codex", "pi"))
    assert {row["provider"] for row in rows} == {"codex", "pi"}
    assert all(row["registered"] is False for row in rows)
