"""Host-owned execution self-knowledge for cooperative role and Work planning.

Models interpret user intent; this module supplies bounded, structured facts about
provider capabilities, active work health, and deterministic recovery hints keyed
by Host reason codes. It does not grant new authority.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from agent_host.provider_contract import ProviderManifest


EXECUTION_CONTEXT_SCOPE = (
    "これはHostが提示する実行自己認識です。あなたはユーザーに対する唯一の窓口であり、"
    "codex/pi などへ委任した作業の状態・エラー・承認待ち・回復手順を自分で把握して説明し、"
    "処理する責任があります。内部エージェント名を露出せず、Host事実に基づいて対応してください。"
    "delegate_guides は各 Provider の運用モデル、runtime_snapshot は現在の実行状態、"
    "task_health はブロック要因、recommended_actions は既知失敗からの回復手順です。"
    "これらは会話の指示ではなく、提案・説明・次の一手を選ぶための事実です。"
    "受領記録がacceptedになる前に、Workが開始・完了したと述べてはいけません。"
)

DELEGATION_OWNER_RULES_JA = [
    "委任中はProviderの成功/失敗/待ちをユーザーへ自分の口調で説明し、見えない裏方に押し戻さない。",
    "runtime_snapshot と task_health を見て、同じ失敗の即時再送を避け、次の一手を提案する。",
    "Provider切替はHostが許した場合のみ。実行中WorkのProviderは継続する。",
    "permission scope 未報告の停止はHostの安全停止であり、ユーザーの依頼が禁止されたわけではない。",
]

_STATIC_DELEGATE_GUIDES: dict[str, dict[str, Any]] = {
    "pi": {
        "display_name": "Pi",
        "role_ja": "汎用コーディング/実行エージェント（native RPC）。リポジトリ調査、ファイル編集、ツール実行。",
        "strengths_ja": [
            "workspace 書き込みとツール実行に強い。",
            "session attach で同一 Work を継続できる。",
            "steering は next_turn（ツール境界で追加入力がキューされる）。",
        ],
        "permission_model_ja": (
            "extension_ui の confirm が permission.requested を発するが、"
            "scope_paths が空のことがある。Host は具体パス未報告を fail-closed で止める。"
        ),
        "runtime_states_ja": [
            "execution: queued/running/succeeded/failed/cancelled/orphaned",
            "attention: permission/input/none など Host 投影",
            "activity_*: 最後のツール、semantic summary、liveness/silent 秒",
        ],
        "common_failures_ja": [
            "permission_scope_missing: 承認対象パス未報告による停止ループ",
            "pi_input_rejected: 実行終端後や不適切なタイミングの追加入力",
            "pi_node_unavailable / pi_authentication_check_failed: 起動不可",
        ],
        "owner_duties_ja": [
            "permission 待ちなら承認UIまたは代替手順を案内する。",
            "scope 未報告ループなら、同じ操作の再送ではなく状態説明と次の選択肢を出す。",
            "別 Provider へ切替える前に現行 Work を停止するか新 Goal に分ける。",
        ],
    },
    "codex": {
        "display_name": "Codex",
        "role_ja": "コーディングエージェント（App Server）。開発、リファクタ、テスト、diff。",
        "strengths_ja": [
            "workspace 書き込み、immediate steering、session attach。",
            "permission は通常 scope_paths を報告し、Host 承認境界が明確。",
            "submission_reconciliation で孤児 run を照会可能。",
        ],
        "permission_model_ja": (
            "ツール/コマンド承認は permission.requested で scope を持つことが多い。"
            "Host 承認後に続行する。"
        ),
        "runtime_states_ja": [
            "execution: queued/running/succeeded/failed/cancelled/orphaned",
            "activity_semantic_summary: Provider 進捗の要約",
            "pending_permissions: 現在の承認待ち一覧",
        ],
        "common_failures_ja": [
            "provider_unavailable: 未登録または起動不可",
            "provider_permission_rejected: ユーザー/Host が拒否",
            "work_recipient_busy: 同一 Work へ重ねた操作",
        ],
        "owner_duties_ja": [
            "承認待ちは具体的な scope をユーザーに短く伝える。",
            "failed/cancelled は last_error と activity を見て原因と次手を説明する。",
            "実行中は同じ codex Work を amend/input で継続する。",
        ],
    },
}


RecoveryEntry = dict[str, Any]

RECOVERY_PLAYBOOK: dict[str, RecoveryEntry] = {
    "planned_work_active_provider_mismatch": {
        "category": "provider_continuity",
        "summary_ja": "既存Workは別のProviderで実行中または継続中です。",
        "recommended_actions_ja": [
            "同じWorkを続けるなら、現在のProviderでamend/inputを出す。",
            "別Providerへ切り替えるなら、先に現行Workを停止するか、新規executeとして別Goalにする。",
            "Provider切替だけではHostは受理しません。",
        ],
    },
    "provider_unavailable": {
        "category": "provider_availability",
        "summary_ja": "指定されたProviderは現在Hostで利用できません。",
        "recommended_actions_ja": [
            "登録済みかつ利用可能なProvider idを確認する。",
            "ユーザーが明示的に選んだProviderが不可なら、その事実を伝え代替を提案する。",
            "黙って別Providerへ切り替えない。",
        ],
    },
    "work_recipient_busy": {
        "category": "execution_busy",
        "summary_ja": "対象Workまたは受信先は現在別の操作を処理中です。",
        "recommended_actions_ja": [
            "同じWorkへの追加入力が必要ならinput/amendを待つか、実行状態をreportで確認する。",
            "別Goalなら新規executeとして扱う。",
            "実行中のWorkを完了したと主張しない。",
        ],
    },
    "work_context_not_settled": {
        "category": "context_settlement",
        "summary_ja": "Workの受信contextまたは配置先がまだ確定していません。",
        "recommended_actions_ja": [
            "scope_changeまたは配置先の選択が必要なら、ユーザーに短く確認する。",
            "contextが確定するまで新しいexecuteを重ねない。",
        ],
    },
    "work_context_changed": {
        "category": "context_settlement",
        "summary_ja": "計画時点からWork contextが変わりました。",
        "recommended_actions_ja": [
            "現在のcurrent_work/task_healthを再確認する。",
            "古い提案をそのまま再送せず、現状に合わせて言い直す。",
        ],
    },
    "work_source_binding_changed": {
        "category": "context_settlement",
        "summary_ja": "Workの会話bindingが計画時と一致しません。",
        "recommended_actions_ja": [
            "現在の受信先とWork rosterを確認する。",
            "対象Workを明示してからamend/retract/reportを出す。",
        ],
    },
    "planned_work_target_unavailable": {
        "category": "target_resolution",
        "summary_ja": "計画したWork対象は現在参照できません。",
        "recommended_actions_ja": [
            "work_tasks/current_workから有効な対象を選び直す。",
            "完了・取消済みWorkをamend対象にしない。",
        ],
    },
    "planned_work_catalog_incomplete": {
        "category": "target_resolution",
        "summary_ja": "Work対象一覧が完全ではないため停止/変更対象を確定できません。",
        "recommended_actions_ja": [
            "reportで現状を確認してから、対象を明示して再提案する。",
            "一覧が不完全な間はretract/amendを出さない。",
        ],
    },
    "role_decision_unavailable": {
        "category": "role_parse",
        "summary_ja": "今回の操作提議をHostが解釈できず、Work受理前に止まりました。",
        "recommended_actions_ja": [
            "ユーザー意図を一つの操作に言い直して確認する。",
            "既存Workの実行状況は変わっていないと伝える。",
        ],
    },
    "work_dispatch_failed": {
        "category": "dispatch",
        "summary_ja": "Work dispatchがHost側で失敗しました。",
        "recommended_actions_ja": [
            "task_healthとreasonを確認する。",
            "同じ内容の即時再送を避け、前提を一つずつ確認する。",
        ],
    },
    "permission_scope_missing": {
        "category": "permission",
        "summary_ja": "Providerが承認対象の具体パスを報告していないため、Hostは安全のため停止しています。",
        "recommended_actions_ja": [
            "承認UIで可能ならallow/denyを選ぶ。",
            "Providerがscopeを報告しない限り同じ操作は繰り返されうる。",
            "別Providerへ切り替える前に、現行Work/permission状態を説明する。",
        ],
    },
    "work_input_owner_unavailable": {
        "category": "input_path",
        "summary_ja": "実行中Workへの追加入力経路が現在利用できません。",
        "recommended_actions_ja": [
            "実行状態をreportで確認する。",
            "Workが終端なら新規executeを検討する。",
        ],
    },
    "planned_work_semantics_unsupported": {
        "category": "plan_shape",
        "summary_ja": "Work計画の形または意味がHost契約外です。",
        "recommended_actions_ja": [
            "一つのintent/targetに分けて再提案する。",
            "未対応機能だと推測せず、Hostが拒否した事実だけを伝える。",
        ],
    },
    "work_owner_ambiguous": {
        "category": "target_resolution",
        "summary_ja": "複数の実行中Workが一致し、停止/変更対象を一意に決められません。",
        "recommended_actions_ja": [
            "work_tasks から対象を一つ明示してもらう。",
            "曖昧なまま retract/amend を出さない。",
        ],
    },
    "provider_permission_rejected": {
        "category": "permission",
        "summary_ja": "Provider操作の承認が拒否され、実行は続行されません。",
        "recommended_actions_ja": [
            "拒否した操作を成功扱いにしない。",
            "別アプローチ、縮小した目標、または再承認の選択肢を提示する。",
        ],
    },
    "pi_input_rejected": {
        "category": "provider_input",
        "summary_ja": "Pi はこのタイミングで追加入力を受け付けませんでした。",
        "recommended_actions_ja": [
            "実行状態を report で確認する。",
            "終端後なら amend/新規 execute を検討する。",
        ],
    },
    "pi_node_unavailable": {
        "category": "provider_availability",
        "summary_ja": "Pi ランタイム（Node/パッケージ）が Host で利用できません。",
        "recommended_actions_ja": [
            "Pi 委任は今は不可と伝える。",
            "可能なら codex など別 Provider をユーザーと明示的に選ぶ。",
        ],
    },
    "pi_authentication_check_failed": {
        "category": "provider_availability",
        "summary_ja": "Pi のモデル認証が未設定または失敗しています。",
        "recommended_actions_ja": [
            "認証設定を直すまで Pi 委任は不可と伝える。",
            "黙って別 Provider に切り替えない。",
        ],
    },
    "adapter_initialization_failed": {
        "category": "provider_availability",
        "summary_ja": "Provider アダプタの初期化に失敗しました。",
        "recommended_actions_ja": [
            "当該 Provider への新規委任は避ける。",
            "登録済みかつ ready の Provider を確認する。",
        ],
    },
}


def _lookup_playbook(reason: str) -> RecoveryEntry | None:
    clean = str(reason or "").strip()
    if not clean:
        return None
    entry = RECOVERY_PLAYBOOK.get(clean)
    if entry is not None:
        return entry
    prefix = clean.split(":", 1)[0]
    return RECOVERY_PLAYBOOK.get(prefix)


def recovery_hints_for_reason(
    reason: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured recovery hints for one Host reason code."""

    entry = _lookup_playbook(reason)
    if entry is None:
        return {}
    hints: dict[str, Any] = {
        "reason": str(reason or "").strip(),
        "category": entry["category"],
        "summary_ja": entry["summary_ja"],
        "recommended_actions_ja": list(entry["recommended_actions_ja"]),
    }
    if isinstance(context, Mapping):
        current_provider = str((context.get("current_work") or {}).get("provider") or "").strip()
        active_provider = str((context.get("active_work") or {}).get("provider") or "").strip()
        planned_provider = str(context.get("planned_provider") or "").strip()
        if current_provider:
            hints["current_provider"] = current_provider
        if active_provider:
            hints["active_provider"] = active_provider
        if planned_provider:
            hints["planned_provider"] = planned_provider
    return hints


def enrich_rejection_receipt(
    receipt: dict[str, Any],
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach recovery hints to a rejected host receipt without changing authority."""

    reason = str(receipt.get("reason") or "").strip()
    hints = recovery_hints_for_reason(reason, context=context)
    if not hints:
        return receipt
    enriched = dict(receipt)
    enriched["recovery"] = hints
    return enriched


def _provider_capability_row(
    provider_id: str,
    requirements: Any,
    manifest: ProviderManifest | None,
) -> dict[str, Any]:
    caps = manifest.capabilities if manifest is not None else None
    return {
        "provider": provider_id,
        "registered": manifest is not None,
        "workspace_access": (
            str(getattr(requirements, "workspace_access", "") or "")
            or (str(caps.workspace_access) if caps is not None else "unknown")
        ),
        "workspace_ownership": (
            str(getattr(requirements, "workspace_ownership", "") or "")
            or (str(caps.workspace_ownership) if caps is not None else "unknown")
        ),
        "interaction": str(caps.interaction if caps is not None else "unknown"),
        "resume": str(caps.resume if caps is not None else "unknown"),
        "steering": str(caps.steering if caps is not None else "unknown"),
    }


def build_capability_brief(
    *,
    context_requirements: Mapping[str, Any],
    manifests: Mapping[str, ProviderManifest | None] | None = None,
) -> dict[str, Any]:
    """Summarize registered provider capabilities for prompt context."""

    providers = []
    for provider_id in sorted(context_requirements):
        manifest = (manifests or {}).get(provider_id) if manifests is not None else None
        providers.append(_provider_capability_row(provider_id, context_requirements[provider_id], manifest))
    return {
        "providers": providers,
        "rules_ja": list(DELEGATION_OWNER_RULES_JA),
    }


def build_delegate_guides(
    *,
    context_requirements: Mapping[str, Any],
    manifests: Mapping[str, ProviderManifest | None] | None = None,
) -> dict[str, Any]:
    """Operational delegate guides for registered Work providers."""

    guides: dict[str, Any] = {}
    for provider_id in sorted(context_requirements):
        static = _STATIC_DELEGATE_GUIDES.get(provider_id)
        if static is None:
            continue
        manifest = (manifests or {}).get(provider_id) if manifests is not None else None
        entry = {key: value for key, value in static.items()}
        entry["registered"] = manifest is not None
        if manifest is not None:
            caps = manifest.capabilities
            entry["capabilities"] = {
                "workspace_access": str(caps.workspace_access),
                "steering": str(caps.steering),
                "resume": str(caps.resume),
                "interaction": str(caps.interaction),
                "append_input": bool(caps.append_input),
            }
        guides[provider_id] = entry
    return guides


def build_provider_readiness(
    *,
    runtime: Any,
    provider_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Summarize which delegate providers are registered and startup-ready."""

    rows: list[dict[str, Any]] = []
    for provider_id in sorted({str(value or "").strip().lower() for value in provider_ids if str(value or "").strip()}):
        manifest = runtime.get_manifest(provider_id) if runtime is not None else None
        adapter = runtime.get_adapter(provider_id) if runtime is not None else None
        row: dict[str, Any] = {
            "provider": provider_id,
            "registered": manifest is not None,
            "ready": manifest is not None,
        }
        startup = getattr(adapter, "_startup_readiness", None) if adapter is not None else None
        if isinstance(startup, Mapping):
            row["startup"] = {
                key: startup[key]
                for key in ("authentication", "version", "diagnostic")
                if key in startup
            }
            if str(startup.get("authentication") or "").strip().lower() == "unavailable":
                row["ready"] = False
        rows.append(row)
    return rows


_RUNTIME_SNAPSHOT_FIELDS = (
    "work_item_id",
    "provider",
    "relation",
    "execution",
    "attention",
    "completion",
    "activity_phase",
    "activity_semantic_summary",
    "activity_last_tool",
    "activity_silent_seconds",
    "activity_liveness",
    "last_error",
    "terminal_status",
    "input_requirements",
)


def enrich_delegate_work_items(coordinator, work_items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Attach provider and terminal error facts from the Work ledger."""

    store = getattr(coordinator, "store", None)
    if store is None:
        return [dict(row) for row in work_items if isinstance(row, Mapping)]
    enriched: list[dict] = []
    for row in work_items:
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        attempt = store.get_attempt(str(row.get("attempt_id") or ""))
        if attempt is not None:
            item["provider"] = attempt.provider
            if attempt.error:
                item["last_error"] = str(attempt.error)[:500]
            if attempt.execution_status in {"failed", "cancelled", "orphaned"}:
                item["terminal_status"] = attempt.execution_status
        enriched.append(item)
    return enriched


def build_delegate_runtime_snapshot(
    work_items: list[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Bounded per-Work runtime facts for delegate troubleshooting."""

    snapshot: list[dict[str, Any]] = []
    for row in work_items or []:
        if not isinstance(row, Mapping):
            continue
        item = {
            key: row[key]
            for key in _RUNTIME_SNAPSHOT_FIELDS
            if key in row and row[key] not in ("", None, [], {})
        }
        if item:
            snapshot.append(item)
    return snapshot[:6]


def _attention_blockers(attention: str, execution: str) -> list[str]:
    blockers: list[str] = []
    clean_attention = str(attention or "").strip().lower()
    clean_execution = str(execution or "").strip().lower()
    if clean_execution in {"queued", "running", "dispatching"}:
        blockers.append("execution_active")
    if clean_attention not in {"", "none"}:
        blockers.append("attention:" + clean_attention)
    return blockers


def build_task_health(
    *,
    current_work: Mapping[str, Any] | None = None,
    active_work: Mapping[str, Any] | None = None,
    work_items: list[Mapping[str, Any]] | None = None,
    pending_permissions: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize active work health and Host-recommended next steps."""

    health: dict[str, Any] = {
        "active_work_item_id": "",
        "active_provider": "",
        "execution_status": "",
        "work_state": "",
        "attention": "",
        "blocked_by": [],
        "pending_permission_count": 0,
        "recommended_actions_ja": [],
    }
    source = current_work if isinstance(current_work, Mapping) else active_work
    if isinstance(source, Mapping):
        health["active_work_item_id"] = str(source.get("work_item_id") or "").strip()
        health["active_provider"] = str(source.get("provider") or "").strip()
        health["execution_status"] = str(source.get("execution_status") or source.get("status") or "").strip()
        health["work_state"] = str(source.get("work_state") or "").strip()
        health["attention"] = str(source.get("attention") or "").strip()
        health["blocked_by"] = _attention_blockers(
            str(source.get("attention") or ""),
            str(source.get("execution_status") or source.get("status") or ""),
        )
        if source.get("input_requirements"):
            health["blocked_by"].append("input_required")
    pending = [row for row in (pending_permissions or []) if isinstance(row, Mapping)]
    health["pending_permission_count"] = len(pending)
    if pending:
        health["blocked_by"].append("permission_pending")
        missing_scope = any(
            not list(row.get("scope") or row.get("scope_paths") or [])
            for row in pending
        )
        if missing_scope:
            health["blocked_by"].append("permission_scope_missing")
            hints = recovery_hints_for_reason("permission_scope_missing")
            health["recommended_actions_ja"].extend(hints.get("recommended_actions_ja") or [])
    running = [
        row for row in (work_items or [])
        if isinstance(row, Mapping) and str(row.get("relation") or "") == "running"
    ]
    if running and not health["active_work_item_id"]:
        first = running[0]
        health["active_work_item_id"] = str(first.get("work_item_id") or "").strip()
        health["execution_status"] = str(first.get("execution") or "").strip()
        health["attention"] = str(first.get("attention") or "").strip()
    if health["blocked_by"]:
        if "permission_scope_missing" in health["blocked_by"]:
            pass
        elif "permission_pending" in health["blocked_by"]:
            health["recommended_actions_ja"].append("保留中の承認を確認するか、実行状態をreportで照会する。")
        elif "input_required" in health["blocked_by"]:
            health["recommended_actions_ja"].append("既存Workへの追加入力/amendを優先し、新規executeで上書きしない。")
        elif "execution_active" in health["blocked_by"]:
            health["recommended_actions_ja"].append("実行中Workは同じProviderで継続する。別Provider切替は停止または新Goalが必要。")
    health["blocked_by"] = list(dict.fromkeys(health["blocked_by"]))
    health["recommended_actions_ja"] = list(dict.fromkeys(health["recommended_actions_ja"]))
    return health


def build_execution_context(
    *,
    context_requirements: Mapping[str, Any],
    manifests: Mapping[str, ProviderManifest | None] | None = None,
    runtime: Any = None,
    current_work: Mapping[str, Any] | None = None,
    active_work: Mapping[str, Any] | None = None,
    work_items: list[Mapping[str, Any]] | None = None,
    pending_permissions: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the structured execution self-knowledge block for model frames."""

    return {
        "delegation_owner_rules_ja": list(DELEGATION_OWNER_RULES_JA),
        "capability_brief": build_capability_brief(
            context_requirements=context_requirements,
            manifests=manifests,
        ),
        "delegate_guides": build_delegate_guides(
            context_requirements=context_requirements,
            manifests=manifests,
        ),
        "provider_readiness": build_provider_readiness(
            runtime=runtime,
            provider_ids=context_requirements.keys(),
        ),
        "runtime_snapshot": build_delegate_runtime_snapshot(work_items),
        "task_health": build_task_health(
            current_work=current_work,
            active_work=active_work,
            work_items=work_items,
            pending_permissions=pending_permissions,
        ),
    }


def render_execution_context_block(context: Mapping[str, Any]) -> str:
    """Render execution context for planner/role prompt appendices."""

    import json

    payload = dict(context)
    return (
        "\n\n[execution_context Host事実]\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n"
        + EXECUTION_CONTEXT_SCOPE
        + "\n[/execution_context Host事実]"
    )
