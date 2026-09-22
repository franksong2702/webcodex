use super::*;

fn read_request(client_id: &str, cwd: &str) -> ShellFileOpRequest {
    ShellFileOpRequest {
        op: "read".to_string(),
        client_id: client_id.to_string(),
        path: "src/lib.rs".to_string(),
        cwd: Some(cwd.to_string()),
        content: None,
        max_bytes: Some(512 * 1024),
        old_text: None,
        pattern: None,
        expected_sha256: None,
        expected_prefix: None,
        start_line: Some(1),
        end_line: Some(10),
        line: None,
        create_dirs: false,
        wait_timeout_secs: 30,
    }
}

async fn register_read_runner(
    registry: &RunnerRegistry,
    client_id: &str,
    instance_id: &str,
    project_path: &str,
) {
    registry
        .register(current_runner_registration(runner_registration(
            client_id,
            instance_id,
            Vec::new(),
        )))
        .await
        .unwrap();
    crate::test_support::apply_project_inventory_snapshot(
        registry,
        client_id,
        instance_id,
        vec![project_summary("demo", project_path)],
    )
    .await;
}

#[tokio::test]
async fn exact_project_read_admission_rejects_runner_replacement_before_enqueue() {
    let registry = RunnerRegistry::default();
    let client_id = "project-read-runner-race";
    register_read_runner(&registry, client_id, "inst-a", "/tmp/project").await;

    registry
        .set_last_seen_for_test(client_id, now_ts() - RUNNER_ONLINE_WINDOW_SECS - 1)
        .await;
    register_read_runner(&registry, client_id, "inst-b", "/tmp/project").await;

    let error = registry
        .enqueue_project_file_read(
            read_request(client_id, "/tmp/project"),
            "demo",
            "/tmp/project",
            "inst-a",
            "tool_runtime".to_string(),
        )
        .await
        .unwrap_err();
    assert!(error.contains("stale_runner"), "{error}");
    assert!(registry
        .poll(RunnerPollRequest {
            client_id: client_id.to_string(),
            runner_instance_id: "inst-b".to_string(),
        })
        .await
        .unwrap()
        .is_none());
}

#[tokio::test]
async fn exact_project_read_admission_rejects_changed_project_placement() {
    let registry = RunnerRegistry::default();
    let client_id = "project-read-placement-race";
    register_read_runner(&registry, client_id, "inst-a", "/tmp/project").await;
    crate::test_support::apply_project_inventory_snapshot(
        &registry,
        client_id,
        "inst-a",
        vec![project_summary("demo", "/tmp/replaced")],
    )
    .await;

    let error = registry
        .enqueue_project_file_read(
            read_request(client_id, "/tmp/project"),
            "demo",
            "/tmp/project",
            "inst-a",
            "tool_runtime".to_string(),
        )
        .await
        .unwrap_err();
    assert!(error.contains("stale_project"), "{error}");
    assert!(registry
        .poll(RunnerPollRequest {
            client_id: client_id.to_string(),
            runner_instance_id: "inst-a".to_string(),
        })
        .await
        .unwrap()
        .is_none());
}

#[tokio::test]
async fn exact_project_read_revalidates_placement_before_dequeue() {
    let registry = RunnerRegistry::default();
    let client_id = "project-read-dequeue-race";
    register_read_runner(&registry, client_id, "inst-a", "/tmp/project").await;
    let (_request_id, response_rx) = registry
        .enqueue_project_file_read(
            read_request(client_id, "/tmp/project"),
            "demo",
            "/tmp/project",
            "inst-a",
            "tool_runtime".to_string(),
        )
        .await
        .unwrap();

    crate::test_support::apply_project_inventory_snapshot(
        &registry,
        client_id,
        "inst-a",
        vec![project_summary("demo", "/tmp/replaced")],
    )
    .await;
    assert!(registry
        .poll(RunnerPollRequest {
            client_id: client_id.to_string(),
            runner_instance_id: "inst-a".to_string(),
        })
        .await
        .unwrap()
        .is_none());
    let response = tokio::time::timeout(std::time::Duration::from_secs(1), response_rx)
        .await
        .expect("stale placement response timed out")
        .expect("stale placement response channel closed");
    assert_eq!(response.request_dispatched, Some(false));
    assert_eq!(
        response.command_execution_state,
        Some(ShellCommandExecutionState::NotStarted)
    );
    assert!(
        response
            .error
            .as_deref()
            .unwrap_or_default()
            .contains("stale_project"),
        "{response:?}"
    );
}

#[tokio::test]
async fn handoff_dequeue_preserves_read_capability_and_revoked_write_guard() {
    for write in [false, true] {
        let registry = RunnerRegistry::default();
        let mut registration =
            current_runner_registration(runner_registration("handoff-fence", "inst", Vec::new()));
        registration.capabilities.project_handoff = true;
        registration.owner = Some("handoff-fixture-owner".into());
        // Generation 2 requires the file_write capability even for read-only
        // projects. Project allow_patch, not the wire baseline, gates writes.
        registry.register(registration).await.unwrap();
        crate::test_support::apply_project_inventory_snapshot(
            &registry,
            "handoff-fence",
            "inst",
            vec![project_summary("demo", "/tmp/project")],
        )
        .await;
        let mut request = read_request("handoff-fence", "/tmp/project");
        request.op = if write {
            "handoff_write"
        } else {
            "handoff_read"
        }
        .into();
        request.path = ".".into();
        request.content = Some(
            serde_json::json!({"action": if write { "append" } else { "status" }}).to_string(),
        );
        request.max_bytes = None;
        request.start_line = None;
        request.end_line = None;
        let access = auth_context(Some("handoff-fixture-owner"), false);
        let (_, rx) = registry
            .enqueue_handoff_file_op(request, "demo", "tool_runtime".into(), Some(&access))
            .await
            .unwrap();
        let mut project = project_summary("demo", "/tmp/project");
        project.allow_patch = false;
        crate::test_support::apply_project_inventory_snapshot(
            &registry,
            "handoff-fence",
            "inst",
            vec![project],
        )
        .await;
        let dispatched = registry
            .poll(RunnerPollRequest {
                client_id: "handoff-fence".into(),
                runner_instance_id: "inst".into(),
            })
            .await
            .unwrap();
        if write {
            assert!(dispatched.is_none());
            let response = tokio::time::timeout(std::time::Duration::from_secs(1), rx)
                .await
                .unwrap()
                .unwrap();
            assert_eq!(response.request_dispatched, Some(false));
            assert!(response.error.unwrap().contains("stale_project"));
        } else {
            assert_eq!(dispatched.unwrap().kind, "file_handoff_read");
        }
    }
}
