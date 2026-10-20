use super::*;
use crate::tool_runtime::model_ergonomics_telemetry::ModelErgonomicsTimer;
use crate::tool_runtime::{ToolResult, ToolRuntime};
use serde_json::{json, Value};

fn arguments(tool: &str, count: usize) -> Value {
    match tool {
        "read_files" => json!({
            "project": "PRIVATE_PROJECT",
            "items": vec![json!({"path": "PRIVATE_PATH", "start_line": 2}); count]
        }),
        "search_project_texts" => json!({
            "project": "PRIVATE_PROJECT",
            "queries": vec![json!({"pattern": "PRIVATE_QUERY", "path": "PRIVATE_PATH"}); count]
        }),
        _ => unreachable!(),
    }
}

fn expected(tool: &str, count: usize) -> Value {
    match tool {
        "read_files" => json!({"kind": tool, "requested_items": count}),
        "search_project_texts" => json!({"kind": tool, "requested_queries": count}),
        _ => unreachable!(),
    }
}

#[test]
fn native_batch_counts_single_and_multiple_canonical_entries_without_payload() {
    for tool in ["read_files", "search_project_texts"] {
        for count in [1, 2, 8] {
            let args = arguments(tool, count);
            let call = ToolCall::from_tool_name(tool, args.clone()).unwrap();
            let mut timer = ModelErgonomicsTimer::start_with_arguments(tool, &args).unwrap();
            timer.capture_admitted_call(&call);
            let completion = timer.finish();
            // A short/mixed result cannot turn requested cardinality into a
            // completed count or replace it with returned cardinality.
            for result in [
                ToolResult::ok(json!({"items": [{"output": "PRIVATE_RESULT"}]})),
                ToolResult::err_with_output("PRIVATE_ERROR", json!({"items": []})),
            ] {
                let api = completion.record_for_tool_result(&result).unwrap();
                let mcp = completion
                    .record_for_structured_content(&serde_json::to_value(&result).unwrap())
                    .unwrap();
                assert_eq!(api, mcp);
                assert_eq!(api.schema_version, 13);
                let record = serde_json::to_value(api).unwrap();
                assert_eq!(record["native_batch"], expected(tool, count));
                assert!(!record.to_string().contains("PRIVATE"));
            }
            let timeout = completion.record_for_pre_result_failure("dispatch_hard_timeout");
            assert_eq!(
                serde_json::to_value(timeout).unwrap()["native_batch"],
                expected(tool, count)
            );
        }
    }
}

#[test]
fn native_batch_is_unavailable_before_admission_and_never_inferred_from_result() {
    for tool in ["read_files", "search_project_texts"] {
        let completion = ModelErgonomicsTimer::start_with_arguments(tool, &arguments(tool, 2))
            .unwrap()
            .finish();
        for record in [
            completion.record_for_pre_result_failure("invalid_arguments"),
            completion
                .record_for_tool_result(&ToolResult::ok(json!({
                    "native_batch": expected(tool, 2),
                    "items": [{}, {}], "queries": [{}, {}]
                })))
                .unwrap(),
        ] {
            assert!(serde_json::to_value(record)
                .unwrap()
                .get("native_batch")
                .is_none());
        }
    }
    let call = ToolCall::from_tool_name("read_tool_manifest", json!({})).unwrap();
    assert!(from_admitted_call(&call).is_none());
    // A different outer tool cannot claim an admitted child's native batch.
    let mut outer = ModelErgonomicsTimer::start("read_tool_manifest").unwrap();
    outer.capture_admitted_call(
        &ToolCall::from_tool_name("read_files", arguments("read_files", 2)).unwrap(),
    );
    assert!(outer
        .finish()
        .record_for_pre_result_failure("invalid_arguments")
        .native_batch
        .is_none());
}

#[test]
fn native_batch_bounds_fail_closed_for_parsed_and_typed_calls() {
    for tool in ["read_files", "search_project_texts"] {
        for count in [0, 9] {
            assert!(ToolCall::from_tool_name(tool, arguments(tool, count)).is_err());
            let mut typed = ToolCall::from_tool_name(tool, arguments(tool, 1)).unwrap();
            match &mut typed {
                ToolCall::ReadFiles { items, .. } => items.resize(count, items[0].clone()),
                ToolCall::SearchProjectTexts { queries, .. } => {
                    queries.resize(count, queries[0].clone());
                }
                _ => unreachable!(),
            }
            assert!(from_admitted_call(&typed).is_none());
        }
        let key = if tool == "read_files" {
            "items"
        } else {
            "queries"
        };
        for invalid in [Value::Null, json!("PRIVATE"), json!([{}])] {
            let mut args = arguments(tool, 1);
            args[key] = invalid;
            assert!(ToolCall::from_tool_name(tool, args).is_err());
        }
    }
}

#[tokio::test]
async fn native_batch_kernel_captures_only_after_canonical_admission() {
    use crate::tool_runtime::kernel::{
        HostFileImportTrust, ToolCallContext, ToolCallRequest, ToolTransport,
    };
    let runtime = ToolRuntime::new_for_tests();
    for tool in ["read_files", "search_project_texts"] {
        for count in [0, 1, 2, 9] {
            let outcome = runtime
                .call_tool_with_context(
                    ToolCallRequest {
                        tool_name: tool.to_string(),
                        arguments: arguments(tool, count),
                    },
                    ToolCallContext {
                        transport: ToolTransport::Api,
                        session_id: None,
                        auth: None,
                        window: None,
                        record_oauth_scope_denials: false,
                        host_file_import_trust: HostFileImportTrust::default(),
                    },
                )
                .await;
            // The unknown Project fails immediately without any Runner I/O.
            // Valid canonical inputs nevertheless represent real invocations;
            // schema rejections carry no admitted cardinality.
            assert!(!outcome.success);
            let completion = outcome.model_ergonomics.unwrap();
            let record = match outcome.result {
                Some(result) => completion.record_for_tool_result(&result).unwrap(),
                None => completion.record_for_pre_result_failure("invalid_arguments"),
            };
            let record = serde_json::to_value(record).unwrap();
            if (1..=8).contains(&count) {
                assert_eq!(record["native_batch"], expected(tool, count));
            } else {
                assert!(record.get("native_batch").is_none());
            }
            assert!(!record.to_string().contains("PRIVATE"));
        }
    }
}
