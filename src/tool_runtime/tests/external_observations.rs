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
        observed_tool: "Bash".into(),
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
    let before_external = runtime.sessions.summary(&session, None).unwrap();
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
    assert_eq!(read.output["coverage"]["complete"], false);
    assert_eq!(
        read.output["coverage"]["reason"],
        "source_sequence_unavailable"
    );
    let after_external = runtime.sessions.summary(&session, None).unwrap();
    assert_eq!(after_external.events_total, before_external.events_total);
    assert_eq!(after_external.events.len(), before_external.events.len());
    assert_eq!(after_external.updated_at, before_external.updated_at);
    let mut conflict = record(&project, &session);
    if let ToolCall::RecordExternalObservation { exit_code, .. } = &mut conflict {
        *exit_code = Some(0);
    }
    let denied = runtime.dispatch_with_auth(conflict, Some(&auth)).await;
    assert!(!denied.success);
    assert_eq!(denied.output["error_kind"], "external_observation_conflict");
    assert_eq!(denied.output["failure_kind"], "conflict");
    assert_eq!(denied.output["state_changed"], false);
    assert_eq!(denied.output["recovery_kind"], "fix_input");

    db.conn_for_tests()
        .execute_batch(
            "CREATE TRIGGER fail_external_observation BEFORE INSERT ON wc_external_observations              BEGIN SELECT RAISE(ABORT,'injected'); END;",
        )
        .unwrap();
    let mut uncertain_call = record(&project, &session);
    if let ToolCall::RecordExternalObservation { event_id, .. } = &mut uncertain_call {
        *event_id = "c".repeat(64);
    }
    let uncertain = runtime
        .dispatch_with_auth(uncertain_call, Some(&auth))
        .await;
    assert!(!uncertain.success);
    assert_eq!(
        uncertain.output["error_kind"],
        "external_observation_storage_uncertain"
    );
    assert_eq!(uncertain.output["failure_kind"], "outcome_unknown");
    assert!(uncertain.output["state_changed"].is_null());
    assert_eq!(uncertain.output["recovery_kind"], "retry_same");
    assert_eq!(uncertain.output["retry_same_event_identity"], true);
    db.conn_for_tests()
        .execute_batch("DROP TRIGGER fail_external_observation")
        .unwrap();

    let mut retry_same = record(&project, &session);
    if let ToolCall::RecordExternalObservation { event_id, .. } = &mut retry_same {
        *event_id = "c".repeat(64);
    }
    let recovered = runtime.dispatch_with_auth(retry_same, Some(&auth)).await;
    assert!(recovered.success, "{recovered:?}");
    assert_eq!(recovered.output["inserted"], true);

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
        2
    );
    // Neither accepting nor reading these reports creates a native Job receipt.
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
    db.conn_for_tests()
        .execute_batch("DROP TABLE wc_external_observations")
        .unwrap();
    let list_failure = runtime
        .dispatch_with_auth(
            ToolCall::ListExternalObservations {
                project: project.clone(),
                session_id: session.clone(),
            },
            Some(&auth),
        )
        .await;
    assert!(!list_failure.success);
    assert_eq!(
        list_failure.output["error_kind"],
        "external_observation_store_unavailable"
    );
    assert_eq!(list_failure.output["state_changed"], false);
    assert_eq!(list_failure.output["recovery_kind"], "reobserve");
    assert!(list_failure
        .output
        .get("retry_same_event_identity")
        .is_none());
}
