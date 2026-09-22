use super::*;
use crate::metadata::{
    ToolPathHint::None as NoPath, PROJECT_READ, PROJECT_WRITE, TOOL_PROVIDER_NATIVE,
};

// Keep both direct MCP entries; the GPT Actions operation budget uses its
// supported gateway route, with identical target authorization.
pub(super) const DEFINITIONS: &[ToolDefinition] = &[
    adaptive_runtime_direct(model_spec(def(
        "project_handoff_read", ToolAuditPolicy::TYPED_CANONICAL,
        ToolVisibility::ModelVisible, "workflow", Some(RunnerCapabilityRequirement::FileRead),
        TOOL_PROVIDER_NATIVE,
        ToolSemanticContract { effect: ToolEffect::Observe, risk: ToolRisk::Read,
            approval: ToolApprovalPolicy::None, idempotency: ToolIdempotency::PureRead },
        Some(PROJECT_READ), true, NoPath, false, false, ToolSessionEvidencePolicy::NONE,
    ), "Read opted-in project-local handoff tasks or one exact checkpoint. During project discovery use authorized listing, search and file-read tools without a task binding; present the exact project to the user before entering work. After the user confirms the project and objective, inspect its tasks, then use project_handoff_write to create or bind the matching task on their behalf. Ask only if the intended task is ambiguous; never choose by recency. Reading does not bind, write, restore a Session or grant authority. Recheck current files and Job state.").with_gpt_action_description("Read project-local handoff tasks or one checkpoint. Does not bind or grant authority. After project/objective confirmation, inspect and reuse the intended task; never choose by recency. Recheck current files and Job state."), 1100).with_gpt_action_gateway_only(),
    adaptive_runtime_direct(permission_risk(requires_explicit_business_session(model_spec(def(
        "project_handoff_write", ToolAuditPolicy::TYPED_CANONICAL,
        ToolVisibility::ModelVisible, "workflow", Some(RunnerCapabilityRequirement::FileWrite),
        TOOL_PROVIDER_NATIVE,
        ToolSemanticContract { effect: ToolEffect::Mutate, risk: ToolRisk::ProjectWrite,
            approval: ToolApprovalPolicy::None, idempotency: ToolIdempotency::NonIdempotent },
        Some(PROJECT_WRITE), true, NoPath, false, false, ToolSessionEvidencePolicy::NONE,
    ), "Create, bind, append to, archive, or disable a project-local handoff checkpoint. After the user confirms the project and objective, handle create/bind on their behalf; do not ask them to configure hooks, supply task IDs or issue binding commands. Read existing tasks first, reuse only the intended task, and never bind merely because a project was found. Requires an authorized write Session and project; a ChatGPT chat ID is not a Workflow Session ID. Project confirmation does not authorize business edits. Keep this Session bound to that project/task. Append uses event_id deduplication and expected_revision; on conflict reread, never overwrite. A failed save does not change prior tool or Job results. No commit, push, deployment, or permission changes.").with_gpt_action_description("Create, bind, append or disable a project handoff after project/objective confirmation. Requires an authorized write Session and project. Reuse the intended task. Append needs event_id and expected_revision; on conflict reread. Save failure never changes prior execution outcomes.")), PERMISSION_RISK_WRITE), 1110).with_gpt_action_gateway_only(),
];
