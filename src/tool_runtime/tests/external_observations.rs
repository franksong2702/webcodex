use super::support::*;
use crate::tool_runtime::session_context::workflow_session_authority_fingerprint;
use crate::tool_runtime::{sessions, ToolCall, ToolRuntime};
use std::sync::Arc;

fn record(project: &str, session: &str) -> ToolCall {
    ToolCall::RecordExternalObservation {
        project: project.into(),
        session_id: session.into(),
        adapter_id: "a".repeat(64),
        event_id: "b".repeat(64),
        tool: "Bash".into(),
        exit_code: None,
    }
}

#[tokio::test]
async fn external_observations_runtime_scope_replay_unknown_and_readback() {
    let tmp = tempfile::tempdir().unwrap();
    let db = Arc::new(crate::db::Database::open(&tmp.path().join("db")).unwrap());
    let runtime = ToolRuntime::new_for_tests().with_communication_database(db.clone());
    let auth = auth_context(None, true);
    let project = register_runner_project_at_path(&runtime, "external", "p", tmp.path()).await;
    let mut opts = sessions::SessionCreateOptions::new(
        Some(project.clone()),
        None,
        Default::default(),
        Default::default(),
    );
    opts.owner_authority_fingerprint =
        Some(workflow_session_authority_fingerprint(Some(&auth)).unwrap());
    let session = runtime
        .sessions
        .start_session_with_options(opts)
        .unwrap()
        .session_id;
    let result = runtime
        .dispatch_with_auth(record(&project, &session), Some(&auth))
        .await;
    assert!(result.success, "{:?}", result);
    assert_eq!(result.output["observation"]["status"], "unknown");
    assert_eq!(result.output["provenance"], "external_report");
    assert_eq!(result.output["inserted"], true);
    let replay = runtime
        .dispatch_with_auth(record(&project, &session), Some(&auth))
        .await;
    assert!(replay.success, "{:?}", replay);
    assert_eq!(replay.output["inserted"], false);
    let read = runtime
        .dispatch_with_auth(
            ToolCall::ListExternalObservations {
                project: project.clone(),
                session_id: session.clone(),
            },
            Some(&auth),
        )
        .await;
    assert!(read.success, "{:?}", read);
    assert_eq!(read.output["observations"].as_array().unwrap().len(), 1);
    let mut conflict = record(&project, &session);
    if let ToolCall::RecordExternalObservation { exit_code, .. } = &mut conflict {
        *exit_code = Some(0);
    }
    let denied = runtime.dispatch_with_auth(conflict, Some(&auth)).await;
    assert!(!denied.success);
    assert_eq!(denied.output["error_kind"], "external_observation_conflict");
    let other = register_runner_project_at_path(&runtime, "external-other", "p", tmp.path()).await;
    assert!(
        !runtime
            .dispatch_with_auth(record(&other, &session), Some(&auth))
            .await
            .success
    );
    let mut stranger = auth_context(Some("stranger"), false);
    stranger.scopes = vec!["admin".into()];
    assert!(
        !runtime
            .dispatch_with_auth(record(&project, &session), Some(&stranger))
            .await
            .success
    );
    let mut no_scope = auth_context(Some("stranger"), false);
    no_scope.scopes = vec!["project:read".into()];
    assert!(
        !runtime
            .dispatch_with_auth(record(&project, &session), Some(&no_scope))
            .await
            .success
    );
    assert_eq!(
        db.list_external_observations(&session, &project)
            .unwrap()
            .len(),
        1
    );
    // Neither accepting nor reading this report creates a native Job receipt.
    assert!(db
        .load_job_receipts(chrono::Utc::now().timestamp())
        .unwrap()
        .is_empty());
    let closed = runtime
        .dispatch_with_auth(
            ToolCall::CloseSession {
                session_id: session.clone(),
            },
            Some(&auth),
        )
        .await;
    assert!(closed.success, "{:?}", closed);
    assert!(
        !runtime
            .dispatch_with_auth(record(&project, &session), Some(&auth))
            .await
            .success
    );
}
