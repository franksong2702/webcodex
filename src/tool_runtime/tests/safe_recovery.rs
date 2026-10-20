//! Canonical dispatch and final model projection of stale transactional batches.
//! Controlled Runner receipts complement the Runner's atomic-write tests; these
//! tests prove the caller can follow the projected reread and reconstruct a fresh
//! batch without gaining blind retry authority or discarding external changes.

use super::support::*;
use crate::runner_protocol::RunnerRequest;
use crate::tool_runtime::kernel::{
    HostFileImportTrust, ToolCallContext, ToolCallRequest, ToolTransport,
};
use crate::tool_runtime::{ToolResult, ToolRuntime};
use serde_json::{json, Value};
use std::fs;
use std::time::{Duration, Instant};
use tokio::task::JoinHandle;

pub(super) fn canonical_call(
    runtime: &ToolRuntime,
    tool: &str,
    arguments: Value,
) -> JoinHandle<ToolResult> {
    let runtime = runtime.clone();
    let tool = tool.to_string();
    tokio::spawn(async move {
        let auth = bootstrap_auth_context();
        let outcome = runtime
            .call_tool_with_context(
                ToolCallRequest {
                    tool_name: tool.clone(),
                    arguments,
                },
                ToolCallContext {
                    transport: ToolTransport::Mcp,
                    session_id: None,
                    auth: Some(&auth),
                    window: None,
                    record_oauth_scope_denials: true,
                    host_file_import_trust: HostFileImportTrust::Untrusted,
                },
            )
            .await;
        assert!(outcome.error_status.is_none(), "{outcome:?}");
        let result = outcome.result.unwrap();
        crate::tool_runtime::startup_brief::validate_schema_instance_for_test(
            &serde_json::to_value(&result).unwrap(),
            &crate::tool_runtime::registry::output_schema_for_tool(&tool),
        )
        .expect("final model result must match the registered output schema");
        result
    })
}

async fn finish_read(
    runtime: &ToolRuntime,
    client: &str,
    task: JoinHandle<ToolResult>,
) -> ToolResult {
    let deadline = Instant::now() + Duration::from_secs(20);
    while !task.is_finished() {
        assert!(Instant::now() < deadline, "canonical read did not finish");
        if let Some(request) = probe_patch_agent_request(runtime, client).await {
            assert_ne!(
                request.kind, "file_apply_text_edits",
                "reread must not write"
            );
            complete_agent_request_by_running_locally(runtime, client, request).await;
        } else {
            tokio::task::yield_now().await;
        }
    }
    let result = task.await.unwrap();
    assert!(result.success, "{result:?}");
    result
}

fn batch(project: &str, first_revision: &Value, second_revision: &Value) -> Value {
    json!({"project":project,"changes":[
        {"kind":"edit","path":"first.txt","expected_read_revision":first_revision,
         "edits":[{"kind":"replace_exact","old_text":"first","new_text":"FIRST"}]},
        {"kind":"edit","path":"second.txt","expected_read_revision":second_revision,
         "edits":[{"kind":"replace_exact","old_text":"second","new_text":"SECOND"}]}
    ]})
}

fn payload(request: &RunnerRequest) -> Value {
    assert_eq!(request.kind, "file_apply_text_edits");
    serde_json::from_str(request.content.as_deref().unwrap()).unwrap()
}

#[tokio::test]
async fn safe_recovery_stale_second_file_rereads_then_reconstructs_guarded_batch() {
    let client = "safe-recovery-batch";
    let root = tempfile::tempdir().unwrap();
    fs::write(root.path().join("first.txt"), "first\n").unwrap();
    fs::write(root.path().join("second.txt"), "second\n").unwrap();
    let runtime = test_runtime();
    let project = register_runner_project_at_path(&runtime, client, "demo", root.path()).await;
    let read = finish_read(
        &runtime,
        client,
        canonical_call(
            &runtime,
            "read_files",
            json!({"project":project,"items":[
                {"path":"first.txt"},{"path":"second.txt"}
            ]}),
        ),
    )
    .await;
    let first_revision = &read.output["items"][0]["output"]["read_revision"];
    let second_revision = &read.output["items"][1]["output"]["read_revision"];
    assert!(first_revision.is_u64() && second_revision.is_u64());
    let stale_arguments = batch(&project, first_revision, second_revision);
    let task = canonical_call(&runtime, "edit_project_files", stale_arguments.clone());
    let request = wait_for_patch_agent_request(&runtime, client).await;
    let wire = payload(&request);
    let hash = |text: &str| crate::tool_runtime::files::sha256_hex_bytes(text.as_bytes());
    assert_eq!(wire["changes"][0]["expected_sha256"], hash("first\n"));
    assert_eq!(wire["changes"][1]["expected_sha256"], hash("second\n"));

    // Change only the second source after the read and before the guarded write.
    let external = "external note\nsecond\n";
    fs::write(root.path().join("second.txt"), external).unwrap();
    complete_patch_agent_request(
        &runtime,
        client,
        &request.request_id,
        0,
        &json!({
            "error":"expected_sha256 mismatch. No files were modified",
            "error_kind":"sha256_conflict","change_index":1,"path":"second.txt",
            "changed":false,"state_changed":false,"rollback_complete":true,
            "conflict_recovery":{"schema_version":1,"conflict_kind":"sha256_mismatch",
                "expected_sha256":hash("second\n"),"current_sha256":hash(external),
                "occurrence_selector_supported":false,"direct_retry_safe":false,
                "reread_required":true,"recovery_action":"reread_file"}
        })
        .to_string(),
        "",
    )
    .await;
    let rejected = task.await.unwrap();
    assert!(!rejected.success, "{rejected:?}");
    assert_eq!(rejected.output["error_kind"], "stale_file_revision");
    assert_eq!(rejected.output["change_index"], 1);
    assert_eq!(rejected.output["state_changed"], false);
    assert_eq!(rejected.output["direct_retry_safe"], false);
    assert_eq!(rejected.output["reread_required"], true);
    assert_eq!(
        fs::read_to_string(root.path().join("first.txt")).unwrap(),
        "first\n"
    );
    assert_eq!(
        fs::read_to_string(root.path().join("second.txt")).unwrap(),
        external
    );
    assert!(rejected.output.get("conflict_recovery").is_none());

    // Use the generated call unchanged, including the exact Project and path.
    let recovery = &rejected.output["recovery"];
    assert_eq!(recovery["follow_up_kind"], "mechanically_followable");
    assert_eq!(recovery["tool"], "read_files");
    assert_eq!(
        recovery["arguments"],
        json!({"project":project,"items":[{"path":"second.txt"}]})
    );
    crate::tool_runtime::startup_brief::validate_schema_instance_for_test(
        &recovery["arguments"],
        &webcodex_tool_contracts::input_schema_for_tool("read_files"),
    )
    .expect("generated reread must validate unchanged against its registered schema");
    let fresh = finish_read(
        &runtime,
        client,
        canonical_call(
            &runtime,
            recovery["tool"].as_str().unwrap(),
            recovery["arguments"].clone(),
        ),
    )
    .await;
    let fresh_item = &fresh.output["items"][0]["output"];
    assert!(fresh_item["text"]
        .as_str()
        .unwrap()
        .contains("external note"));
    let fresh_revision = &fresh_item["read_revision"];
    assert_ne!(fresh_revision, second_revision);
    let fresh_arguments = batch(&project, first_revision, fresh_revision);
    assert_ne!(
        fresh_arguments, stale_arguments,
        "recovery constructs a new guarded call"
    );
    let task = canonical_call(&runtime, "edit_project_files", fresh_arguments);
    let request = wait_for_patch_agent_request(&runtime, client).await;
    let wire = payload(&request);
    assert_eq!(wire["changes"][0]["expected_sha256"], hash("first\n"));
    assert_eq!(wire["changes"][1]["expected_sha256"], hash(external));

    // The controlled successful receipt preserves external content and gives
    // each changed file a new strong read revision in the final projection.
    fs::write(root.path().join("first.txt"), "FIRST\n").unwrap();
    fs::write(root.path().join("second.txt"), "external note\nSECOND\n").unwrap();
    complete_patch_agent_request(
        &runtime,
        client,
        &request.request_id,
        0,
        &json!({
            "dry_run":false,"applied_count":2,"changed":true,"would_change":true,
            "change_summary":{"requested_changes":2,"changed_files":2,
                "logical_edits":2,"resolved_matches":2,"warnings":0},
            "changed_paths":["first.txt","second.txt"],"files":[
                {"index":0,"kind":"edit","path":"first.txt","to_path":null,
                 "old_sha256":hash("first\n"),"new_sha256":hash("FIRST\n"),
                 "changed":true,"would_change":true,"edits":[{
                    "index":0,"kind":"replace_exact","old_start_line":1,
                    "old_end_line":1,"new_line_count":1,"would_change":true}]},
                {"index":1,"kind":"edit","path":"second.txt","to_path":null,
                 "old_sha256":hash(external),"new_sha256":hash("external note\nSECOND\n"),
                 "changed":true,"would_change":true,"edits":[{
                    "index":0,"kind":"replace_exact","old_start_line":2,
                    "old_end_line":2,"new_line_count":1,"would_change":true}]}
            ]
        })
        .to_string(),
        "",
    )
    .await;
    let applied = task.await.unwrap();
    assert!(applied.success, "{applied:?}");
    assert_eq!(applied.output["changed"], true);
    assert_eq!(applied.output["files"].as_array().unwrap().len(), 2);
    for file in applied.output["files"].as_array().unwrap() {
        assert!(file["read_revision"].is_u64(), "{applied:?}");
    }
    assert_eq!(
        fs::read_to_string(root.path().join("first.txt")).unwrap(),
        "FIRST\n"
    );
    assert_eq!(
        fs::read_to_string(root.path().join("second.txt")).unwrap(),
        "external note\nSECOND\n"
    );
    assert!(
        probe_patch_agent_request(&runtime, client).await.is_none(),
        "no automatic retry"
    );
}
