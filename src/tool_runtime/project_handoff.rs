//! Project-file handoff adapter. Session identity is explicit; this is neither
//! a Session replacement nor execution/retry authority.
use super::{project_resolution::ResolvedProject, ToolCall, ToolResult, ToolRuntime};
use crate::auth::AuthContext;
use crate::runner_protocol::ShellFileOpRequest;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::time::Duration;

pub(crate) fn client_key(session_id: &str) -> String {
    format!("webcodex:{:x}", Sha256::digest(session_id.as_bytes()))
}

impl ToolRuntime {
    pub(crate) async fn project_handoff_for_startup(
        &self,
        project: &str,
        session: &str,
        auth: Option<&AuthContext>,
    ) -> Option<Value> {
        let resolved = self
            .resolve_project_input_for_auth(project, auth)
            .await
            .ok()?;
        let access = crate::runner_http::runner_access_from_auth(auth);
        if !self
            .runner_registry
            .runner_supports_for_auth(
                &resolved.config.client_id,
                crate::runner_protocol::RUNNER_CAPABILITY_PROJECT_HANDOFF,
                access.as_ref(),
            )
            .await
            .unwrap_or(false)
        {
            return None;
        }
        match self
            .handoff_runner_request(
                &resolved,
                false,
                json!({"action":"status","client_id":client_key(session)}),
                auth,
            )
            .await
        {
            Ok(mut value) if value["enabled"] == true => {
                self.add_handoff_source_status(&resolved, &mut value);
                Some(value)
            }
            Ok(_) => None,
            Err(_) => Some(
                json!({"status":"unavailable","hint":"Do not infer that no prior task exists."}),
            ),
        }
    }

    fn add_handoff_source_status(&self, resolved: &ResolvedProject, value: &mut Value) {
        value["source_status"] = match self.project_handoff_db.as_ref().and_then(|db| {
            db.handoff_source_status(
                &resolved.resolved_id,
                &resolved.config.path,
                value["task_id"].as_str(),
                value
                    .pointer("/checkpoint/project_identity/root_fingerprint")
                    .and_then(Value::as_str),
            )
            .ok()
        }) {
            Some(status) => status,
            None => json!({"status":"unavailable","coverage":"unknown"}),
        };
        value["source_pending_facts"] = value["source_status"]["pending"].clone();
    }

    pub(crate) fn capture_handoff_fact(
        &self,
        start: Option<&super::sessions::ToolCallStart>,
        result: &ToolResult,
    ) -> Option<Value> {
        let start = start?;
        if start.logical_invocation_role.as_deref() == Some("recorder")
            || result.output["execution_state"] == "not_started"
            || start.tool_name.starts_with("project_handoff_")
            || !(start.write_like || start.shell_like)
        {
            return None;
        }
        let db = self.project_handoff_db.as_ref()?;
        let binding = match db.handoff_binding(&start.session_id) {
            Ok(Some(binding)) => binding,
            Ok(None) => return None,
            Err(_) => return Some(json!({"status":"failed","reason":"outbox_unavailable"})),
        };
        if start.resolved_project.as_deref() != Some(binding.project_id.as_str()) {
            return Some(json!({"status":"failed","reason":"event_project_mismatch"}));
        }
        let identity = start
            .logical_invocation_id
            .as_deref()
            .unwrap_or(&start.call_id);
        let mut event = json!({"type":"tool_finished","source":"webcodex",
            "event_id":format!("tool-{:x}", Sha256::digest(format!("{}\0{}",start.session_id,identity))),
            "tool":start.tool_name,"success":result.success,
            "status":if result.success { "tool_succeeded" } else { "tool_failed" },
            "observed_at":start.started_at,
        });
        if !start.changed_paths.is_empty() {
            event["paths"] = json!(start.changed_paths.iter().take(32).collect::<Vec<_>>());
            if start.changed_paths.len() > 32 {
                event["unknown"] = true.into();
                event["status"] = "partial_path_coverage".into();
            }
        }
        if let Some(code) = result.output.get("exit_code").and_then(Value::as_i64) {
            event["exit_code"] = code.into();
        }
        // The admission result is not a terminal verdict, but its exact Job
        // handle must survive a switch before the Runner's next callback.
        if let Some(job_id) = result.output.get("job_id").and_then(Value::as_str) {
            if !job_id.is_empty()
                && job_id.len() <= 128
                && job_id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
            {
                event["job_id"] = job_id.into();
            }
        }
        match db.handoff_enqueue(&start.session_id, &event, start.started_at) {
            Ok(()) => Some(json!({"status":"pending"})),
            Err(_) => {
                let _ = db.handoff_capture_gap(&start.session_id);
                Some(json!({"status":"failed","reason":"fact_not_saved"}))
            }
        }
    }

    pub(crate) async fn handoff_admission(
        &self,
        resolved: &ResolvedProject,
        session: Option<&str>,
        auth: Option<&AuthContext>,
    ) -> Result<(), ToolResult> {
        if let (Some(db), Some(session)) = (&self.project_handoff_db, session) {
            match db.handoff_binding(session) {
                Ok(Some(binding)) => {
                    if db.handoff_retirement_started(&binding).unwrap_or(true) {
                        return Err(ToolResult::err_with_output(
                            "handoff_task_retired_or_retiring",
                            json!({"execution_state":"not_started"}),
                        ));
                    }
                }
                Ok(None) => {}
                Err(_) => return Err(ToolResult::err("handoff_binding_unavailable")),
            }
        }
        let access = crate::runner_http::runner_access_from_auth(auth);
        if !self
            .runner_registry
            .runner_supports_for_auth(
                &resolved.config.client_id,
                crate::runner_protocol::RUNNER_CAPABILITY_PROJECT_HANDOFF,
                access.as_ref(),
            )
            .await
            .unwrap_or(false)
        {
            return Ok(());
        }
        let mut request = json!({"action":"status"});
        if let Some(session) = session {
            request["client_id"] = client_key(session).into();
        }
        let state = self
            .handoff_runner_request(resolved, false, request, auth)
            .await
            .map_err(|_| {
                ToolResult::err(
                    "handoff_state_unavailable: cannot confirm task attribution before execution",
                )
            })?;
        if state["enabled"] != true {
            return Ok(());
        }
        let binding = session.and_then(|session| {
            self.project_handoff_db
                .as_ref()
                .and_then(|db| db.handoff_binding(session).ok().flatten())
        });
        if binding.as_ref().is_some_and(|b| {
            b.project_id == resolved.resolved_id
                && b.project_path == resolved.config.path
                && b.client_id == resolved.config.client_id
                && state["bound_task_id"].as_str() == Some(b.task_id.as_str())
        }) {
            return Ok(());
        }
        Err(ToolResult::err_with_output("handoff_task_selection_required: use project_handoff_read and explicitly bind the intended task before retrying",
            json!({"error_kind":"handoff_task_selection_required","execution_state":"not_started"})))
    }

    pub(crate) async fn dispatch_project_handoff(
        &self,
        call: ToolCall,
        auth: Option<&AuthContext>,
    ) -> ToolResult {
        let explicit_session = call.session_id().map(str::to_owned);
        let (project, write, request) = match call {
            ToolCall::ProjectHandoffRead {
                project,
                task_id,
                session_id,
            } => {
                let request = match task_id {
                    Some(task_id) => json!({"action":"read","task_id":task_id}),
                    None => match session_id {
                        Some(session_id) => {
                            json!({"action":"status","client_id":client_key(&session_id)})
                        }
                        None => json!({"action":"status"}),
                    },
                };
                (project, false, request)
            }
            ToolCall::ProjectHandoffWrite {
                project,
                session_id,
                request,
            } => {
                let mut request =
                    serde_json::to_value(request).expect("typed handoff request serializes");
                let Some(object) = request.as_object_mut() else {
                    return ToolResult::err("invalid_handoff_request");
                };
                if object.contains_key("client_id") || object.contains_key("binding") {
                    return ToolResult::err("handoff client identity is Server-owned");
                }
                if let Some(event) = object.get_mut("event") {
                    let Some(event) = event.as_object_mut() else {
                        return ToolResult::err("invalid_handoff_event");
                    };
                    if !matches!(
                        event.get("type").and_then(Value::as_str),
                        Some(
                            "note_added"
                                | "stage_started"
                                | "stage_finished"
                                | "task_completed"
                                | "task_blocked"
                        )
                    ) {
                        return ToolResult::err("model-authored handoff entries must be notes or explicit task judgments");
                    }
                    event.insert("source".into(), json!("gpt"));
                }
                if object.get("action").and_then(Value::as_str) == Some("bind") {
                    object.insert("client_id".into(), json!(client_key(&session_id)));
                }
                (project, true, request)
            }
            _ => unreachable!("only project handoff calls route here"),
        };
        let resolved = match self.resolve_project_input_for_auth(&project, auth).await {
            Ok(resolved) => resolved,
            Err(error) => return error.into_tool_result(),
        };
        if write && !resolved.config.allow_patch {
            return ToolResult::err("project_handoff_write requires allow_patch=true");
        }
        if write && request["action"] == "archive" {
            return self
                .archive_project_handoff(&resolved, &request, auth)
                .await;
        }
        if write && request["action"] == "bind" {
            let Some(db) = &self.project_handoff_db else {
                return ToolResult::err("handoff durable delivery is unavailable");
            };
            let Some(task_id) = request["task_id"].as_str() else {
                return ToolResult::err("handoff bind requires exact task_id");
            };
            let checkpoint = match self
                .handoff_runner_request(
                    &resolved,
                    false,
                    json!({"action":"read","task_id":task_id}),
                    auth,
                )
                .await
            {
                Ok(checkpoint) => checkpoint,
                Err(code) => return ToolResult::err(code),
            };
            let Some(fingerprint) = checkpoint
                .pointer("/checkpoint/project_identity/root_fingerprint")
                .and_then(Value::as_str)
            else {
                return ToolResult::err("handoff project identity unavailable");
            };
            let binding = crate::db::HandoffBinding {
                session_id: explicit_session.clone().unwrap_or_default(),
                project_id: resolved.resolved_id.clone(),
                client_id: resolved.config.client_id.clone(),
                project_path: resolved.config.path.clone(),
                task_id: task_id.into(),
                root_fingerprint: fingerprint.into(),
            };
            if db.handoff_bind(&binding).is_err() {
                return ToolResult::err("handoff_binding_not_saved_or_conflicting");
            }
        }
        let binding_write = write && request["action"] == "bind";
        match self
            .handoff_runner_request(&resolved, write, request, auth)
            .await
        {
            Ok(mut output) => {
                if binding_write {
                    output["checkpoint_persistence"] = self
                        .flush_project_handoff(
                            explicit_session.as_deref().unwrap_or_default(),
                            auth,
                        )
                        .await;
                }
                self.add_handoff_source_status(&resolved, &mut output);
                ToolResult::ok(output)
            }
            Err(code) => ToolResult::err_with_output(
                code.clone(),
                json!({"checkpoint_status":
                if code == "handoff_save_unknown" { "unknown" } else { "failed" },"error_kind":code}),
            ),
        }
    }

    async fn archive_project_handoff(
        &self,
        resolved: &ResolvedProject,
        request: &Value,
        auth: Option<&AuthContext>,
    ) -> ToolResult {
        let Ok(_exclusive) = self.handoff_retirement_gate.try_write() else {
            return ToolResult::err_with_output(
                "handoff_retirement_busy",
                json!({"execution_state":"not_started"}),
            );
        };
        let Some(db) = &self.project_handoff_db else {
            return ToolResult::err("handoff_delivery_unavailable");
        };
        let Some(task_id) = request["task_id"].as_str() else {
            return ToolResult::err("task_id_required");
        };
        let access = crate::runner_http::runner_access_from_auth(auth);
        if self
            .runner_registry
            .count_active_jobs_for_project(access.as_ref(), &resolved.resolved_id)
            .await
            != 0
        {
            return ToolResult::err("handoff_active_jobs");
        }
        let checkpoint = match self
            .handoff_runner_request(
                resolved,
                false,
                json!({"action":"read","task_id":task_id}),
                auth,
            )
            .await
        {
            Ok(value) => value,
            Err(code) => return ToolResult::err(code),
        };
        let Some(fingerprint) = checkpoint
            .pointer("/checkpoint/project_identity/root_fingerprint")
            .and_then(Value::as_str)
        else {
            return ToolResult::err("handoff_identity_unavailable");
        };
        let identity = crate::db::HandoffBinding {
            session_id: String::new(),
            project_id: resolved.resolved_id.clone(),
            client_id: resolved.config.client_id.clone(),
            project_path: resolved.config.path.clone(),
            task_id: task_id.into(),
            root_fingerprint: fingerprint.into(),
        };
        if checkpoint["revision"] != request["expected_revision"]
            || checkpoint["checkpoint"]["status"] != "completed"
            || checkpoint["checkpoint"]["unknown_count"] != 0
            || checkpoint["jobs_truncated"] == true
            || checkpoint["jobs"]
                .as_array()
                .is_none_or(|jobs| jobs.iter().any(|j| j["terminal"] != true))
        {
            // A fresh read proving the task is not archived reconciles an
            // earlier unknown response. Never leave resolved non-archival frozen.
            if checkpoint["archived"] == false {
                if db.handoff_cancel_retirement(&identity).is_err() {
                    return ToolResult::err("handoff_retirement_reconciliation_failed");
                }
            }
            return ToolResult::err("handoff_task_unresolved_or_stale");
        }
        if db.handoff_retire(&identity, false).is_err() {
            return ToolResult::err("handoff_retirement_unresolved_or_full");
        }
        match self
            .handoff_runner_request(resolved, true, request.clone(), auth)
            .await
        {
            Ok(mut output) => {
                if db.handoff_retire(&identity, true).is_err() {
                    return ToolResult::err_with_output(
                        "handoff_retirement_pending",
                        json!({"checkpoint":output,"retirement":"pending","retry":"read exact task and retry archive; do not replay business work"}),
                    );
                }
                output["retirement"] = json!("retired");
                output["source_status"] = db
                    .handoff_source_status(
                        &identity.project_id,
                        &identity.project_path,
                        Some(&identity.task_id),
                        Some(&identity.root_fingerprint),
                    )
                    .unwrap_or_else(|_| json!({"status":"unavailable","coverage":"unknown"}));
                output["source_pending_facts"] = output["source_status"]["pending"].clone();
                ToolResult::ok(output)
            }
            Err(code) => {
                let cancelled = code != "handoff_save_unknown"
                    && checkpoint["archived"] != true
                    && db.handoff_cancel_retirement(&identity).is_ok();
                ToolResult::err_with_output(
                    code,
                    json!({"retirement":if cancelled {"not_archived"} else {"pending"},"retry":"read exact task and retry archive; do not replay business work"}),
                )
            }
        }
    }

    /// Deliver already-recorded facts only while current Session, scope,
    /// project, and local opt-in still authorize the exact target.
    pub(crate) async fn flush_project_handoff(
        &self,
        session_id: &str,
        auth: Option<&AuthContext>,
    ) -> Value {
        let Some(db) = &self.project_handoff_db else {
            return json!({"status":"disabled"});
        };
        let binding = match db.handoff_binding(session_id) {
            Ok(Some(binding)) => binding,
            Ok(None) => return json!({"status":"disabled"}),
            Err(_) => return json!({"status":"failed","reason":"outbox_unavailable"}),
        };
        if !self.permission_evaluator.config().auto_authorize()
            || auth.is_some_and(|auth| !auth.has_scope(crate::auth::SCOPE_PROJECT_WRITE))
            || self
                .sessions
                .guard_state(session_id)
                .is_none_or(|(mode, guards)| {
                    super::sessions::SessionGuards::effective(mode, guards).deny_write_tools
                })
        {
            return json!({"status":"pending","reason":"write_authority_unavailable"});
        }
        let resolved = match self
            .resolve_project_input_for_auth(&binding.project_id, auth)
            .await
        {
            Ok(resolved)
                if resolved.config.allow_patch
                    && resolved.config.path == binding.project_path
                    && resolved.config.client_id == binding.client_id =>
            {
                resolved
            }
            _ => return json!({"status":"pending","reason":"project_authority_changed"}),
        };
        let selection = match self
            .handoff_runner_request(
                &resolved,
                false,
                json!({"action":"status","client_id":client_key(session_id)}),
                auth,
            )
            .await
        {
            Ok(selection) => selection,
            Err(_) => return json!({"status":"pending","reason":"runner_unavailable"}),
        };
        if selection["enabled"] != true || selection["bound_task_id"] != binding.task_id {
            return json!({"status":"pending","reason":"local_binding_changed_or_disabled"});
        }
        let pending = match db.handoff_pending_for_task(&binding) {
            Ok(pending) => pending,
            Err(_) => return json!({"status":"failed","reason":"outbox_unavailable"}),
        };
        // One deadline for the complete bounded batch; caller never waits 32
        // independent timeout windows. Cancellation leaves unacked facts pending.
        let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
        for item in pending {
            let result = tokio::time::timeout_at(deadline, async {
                let current = self
                    .handoff_runner_request(
                        &resolved,
                        false,
                        json!({"action":"read","task_id":binding.task_id}),
                        auth,
                    )
                    .await?;
                if current
                    .pointer("/checkpoint/project_identity/root_fingerprint")
                    .and_then(Value::as_str)
                    != Some(binding.root_fingerprint.as_str())
                {
                    return Err("project_identity_changed".into());
                }
                let revision = current["revision"]
                    .as_u64()
                    .ok_or("invalid_checkpoint_revision")?;
                self.handoff_runner_request(
                    &resolved,
                    true,
                    json!({"action":"append",
                    "task_id":binding.task_id,"expected_revision":revision,"event":item.event}),
                    auth,
                )
                .await
            })
            .await;
            if !matches!(result, Ok(Ok(_))) {
                return json!({"status":"pending","reason":"delivery_unconfirmed"});
            }
            if db.handoff_ack(&item.session_id, &item.event_id).is_err() {
                return json!({"status":"pending","reason":"ack_unconfirmed"});
            }
        }
        match db.handoff_pending_for_task(&binding) {
            Ok(items) if items.is_empty() => json!({"status":"saved","task_id":binding.task_id}),
            _ => json!({"status":"pending","reason":"more_pending_facts"}),
        }
    }

    pub(crate) async fn handoff_runner_request(
        &self,
        resolved: &ResolvedProject,
        write: bool,
        request: Value,
        auth: Option<&AuthContext>,
    ) -> Result<Value, String> {
        let content = serde_json::to_string(&request).map_err(|_| "invalid_handoff_request")?;
        if content.len() > 128 * 1024 {
            return Err("handoff_request_too_large".into());
        }
        let prefix = format!("agent:{}:", resolved.config.client_id);
        let agent_project_id = resolved
            .resolved_id
            .strip_prefix(&prefix)
            .filter(|id| !id.is_empty())
            .ok_or("handoff_invalid_project_identity")?;
        let access = crate::runner_http::runner_access_from_auth(auth);
        let (id, receiver) = self
            .runner_registry
            .enqueue_handoff_file_op(
                ShellFileOpRequest {
                    op: if write {
                        "handoff_write"
                    } else {
                        "handoff_read"
                    }
                    .into(),
                    client_id: resolved.config.client_id.clone(),
                    cwd: Some(resolved.config.path.clone()),
                    path: ".".into(),
                    content: Some(content),
                    max_bytes: None,
                    old_text: None,
                    pattern: None,
                    expected_sha256: None,
                    expected_prefix: None,
                    start_line: None,
                    end_line: None,
                    line: None,
                    create_dirs: false,
                    wait_timeout_secs: 5,
                },
                agent_project_id,
                "project_handoff".into(),
                access.as_ref(),
            )
            .await
            .map_err(|_| "handoff_unavailable")?;
        let response = match tokio::time::timeout(Duration::from_secs(5), receiver).await {
            Ok(Ok(response)) => response,
            _ => {
                self.runner_registry.cancel_request(&id).await;
                // A timeout never proves that a write did not land. The stable
                // event_id and revision must be reconciled, not blindly replayed.
                return Err(if write {
                    "handoff_save_unknown"
                } else {
                    "handoff_unavailable"
                }
                .into());
            }
        };
        let unconfirmed = if write {
            "handoff_save_unknown"
        } else {
            "handoff_invalid_response"
        };
        let text = response.stdout.as_deref().ok_or(unconfirmed)?;
        if text.len() > 512 * 1024 {
            return Err(unconfirmed.into());
        }
        let value: Value = serde_json::from_str(text).map_err(|_| unconfirmed)?;
        if response.exit_code != Some(0) || response.error.is_some() || value["success"] != true {
            if write && value["error"]["state_changed"] != false {
                return Err("handoff_save_unknown".into());
            }
            // Only stable codes cross the boundary, never raw Runner output.
            let code = value["error"]["code"].as_str().filter(|code| {
                !code.is_empty()
                    && code.len() <= 64
                    && code.bytes().all(|b| b.is_ascii_lowercase() || b == b'_')
            });
            return Err(code.unwrap_or("handoff_save_failed").into());
        }
        let output = value
            .get("output")
            .filter(|v| v.is_object())
            .cloned()
            .ok_or(unconfirmed)?;
        if !write {
            match output["enabled"].as_bool() {
                Some(false) if output["status"] == "disabled" => {}
                Some(true)
                    if request["action"] == "status"
                        && output["status"] == "enabled"
                        && output["tasks"].is_array() => {}
                Some(true)
                    if request["action"] == "read"
                        && output["status"] == "ready"
                        && output["task_id"] == request["task_id"]
                        && output["checkpoint"]["task_id"] == request["task_id"]
                        && output["revision"].as_u64().is_some_and(|r| r > 0) => {}
                _ => return Err(unconfirmed.into()),
            }
        }
        // An append acknowledgement must identify exactly the persisted event.
        // A generic successful response cannot justify deleting the outbox row.
        if request["action"] == "append"
            && (output["task_id"] != request["task_id"]
                || output["event_id"] != request["event"]["event_id"]
                || !matches!(output["status"].as_str(), Some("saved" | "duplicate"))
                || output["revision"].as_u64().filter(|v| *v > 0).is_none())
        {
            return Err(unconfirmed.into());
        }
        if write {
            let confirmed = match request["action"].as_str() {
                Some("append") => true, // Exact event acknowledgement checked above.
                Some("create") => {
                    output["status"] == "saved"
                        && output["task_id"] == request["task_id"]
                        && output["revision"].as_u64().is_some_and(|r| r > 0)
                }
                Some("bind") => {
                    output["status"] == "bound"
                        && output["task_id"] == request["task_id"]
                        && output["bound_task_id"] == request["task_id"]
                        && output["client_id"] == request["client_id"]
                }
                Some("archive") => {
                    output["status"] == "archived"
                        && output["task_id"] == request["task_id"]
                        && output["revision"] == request["expected_revision"]
                }
                Some("disable") => output["status"] == "disabled" && output["enabled"] == false,
                _ => false,
            };
            if !confirmed {
                return Err(unconfirmed.into());
            }
        }
        Ok(output)
    }
}
