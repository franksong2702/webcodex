//! External reports never enter native execution/validation projections.
use super::{ToolResult, ToolRuntime};
use crate::auth::AuthContext;
use serde_json::{json, Value};
use webcodex_store::{ExternalObservation, ExternalObservationError};

fn project_observation(value: ExternalObservation) -> Value {
    let status = match value.exit_code {
        Some(0) => "reported_success",
        Some(_) => "reported_failure",
        None => "unknown",
    };
    let mut result = serde_json::to_value(value).expect("observation serializes");
    result["status"] = json!(status);
    result
}

impl ToolRuntime {
    pub(crate) async fn external_observation_tool(
        &self,
        project: String,
        session_id: String,
        input: Option<ExternalObservation>,
        auth: Option<&AuthContext>,
    ) -> ToolResult {
        let name = if input.is_some() {
            "record_external_observation"
        } else {
            "list_external_observations"
        };
        if let Err(result) = self.authorize_session_target(&session_id, name, auth).await {
            return result;
        }
        let resolved = match self.resolve_project_input_for_auth(&project, auth).await {
            Ok(value) => value,
            Err(error) => return error.into_tool_result(),
        };
        let Some(summary) = self.sessions.summary(&session_id, Some(0)) else {
            return super::session_context::unknown_session_result(&session_id);
        };
        if project != resolved.resolved_id || summary.project.as_deref() != Some(project.as_str()) {
            return ToolResult::err_with_output(
                "External observations require the exact Session Project",
                json!({
                    "error_kind":"session_project_mismatch", "state_changed":false,
                }),
            );
        }
        if input.is_some() && !summary.lifecycle.allows_mutation() {
            return ToolResult::err_with_output(
                "Session is closed",
                json!({"error_kind":"session_closed", "state_changed":false}),
            );
        }
        let Some(db) = self.communication_db.as_ref() else {
            return ToolResult::err("external_observation_store_unavailable");
        };
        let result = if let Some(input) = input {
            db.record_external_observation(&session_id, &project, input)
                .map(|(record, inserted)| {
                    json!({
                        "session_id":session_id, "project":project, "provenance":"external_report",
                        "inserted":inserted, "observation":project_observation(record),
                    })
                })
        } else {
            db.list_external_observations(&session_id, &project).map(|rows| json!({
                "session_id":session_id, "project":project, "provenance":"external_report",
                "observations": rows.into_iter().map(project_observation).collect::<Vec<_>>(),
            }))
        };
        match result {
            Ok(output) => ToolResult::ok(output),
            Err(error) => {
                let code = match error {
                    ExternalObservationError::InvalidInput => "invalid_external_observation",
                    ExternalObservationError::Conflict => "external_observation_conflict",
                    ExternalObservationError::Capacity => "external_observation_capacity",
                    ExternalObservationError::Storage => "external_observation_storage_unavailable",
                };
                // A commit failure may have an uncertain outcome. Do not claim
                // state_changed=false or suggest a fresh identity/business retry.
                ToolResult::err_with_output(
                    code,
                    json!({"error_kind":code,
                    "recovery":"Reconcile using the same Session, adapter and event identity; never replay the business operation."}),
                )
            }
        }
    }
}
