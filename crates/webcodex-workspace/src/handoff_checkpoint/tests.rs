use super::*;
use serde_json::json;
use std::fs;
use std::sync::Arc;

#[test]
fn duplicate_repairs_stale_markdown_without_losing_human_notes() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("repair", "Repair")).unwrap();
    let path = root.path().join("handoff/repair.md");
    let old = fs::read_to_string(&path).unwrap();
    let request = append_request("repair", 1, "terminal", "failed");
    execute(root.path(), request.clone()).unwrap();
    fs::write(&path, format!("{old}\n用户补充：尚待确认。\n")).unwrap();
    let result = execute(root.path(), request).unwrap();
    assert_eq!(result["status"], "duplicate");
    let repaired = fs::read_to_string(&path).unwrap();
    assert!(repaired.contains("terminal"));
    assert!(repaired.contains("用户补充：尚待确认。"));
}

#[test]
fn markdown_edit_after_projection_read_is_preserved() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("edit", "Edit")).unwrap();
    let project = open_project_root(root.path()).unwrap();
    with_write_lock(&project, |handoff| {
        let task = load_task(handoff, &project.identity, "edit")?;
        let plan = markdown_plan(handoff, "edit.md", &task)?;
        let path = root.path().join("handoff/edit.md");
        let user_bytes = b"User changed the existing file after projection read.";
        fs::write(&path, user_bytes).unwrap();
        let failure = atomic_write_checked(
            handoff,
            "edit.md",
            plan.bytes.as_deref().unwrap(),
            true,
            Some(plan.original.as_deref()),
        )
        .unwrap_err();
        assert_eq!(code(&failure), "markdown_conflict");
        assert_eq!(fs::read(path).unwrap(), user_bytes);
        Ok(())
    })
    .unwrap();
}

fn create_request(task_id: &str, title: &str) -> Value {
    json!({"action":"create","task_id":task_id,"title":title})
}

fn event(event_id: &str, status: &str) -> Value {
    json!({
        "event_id": event_id,
        "type": "job_terminal",
        "source": "local_codex",
        "job_id": "job-1",
        "status": status,
        "summary": "bounded result",
    })
}

fn append_request(task_id: &str, revision: u64, event_id: &str, status: &str) -> Value {
    json!({
        "action": "append",
        "task_id": task_id,
        "expected_revision": revision,
        "event": event(event_id, status),
    })
}

fn code(error: &Value) -> &str {
    error["code"].as_str().expect("stable error code")
}

#[test]
fn status_and_read_without_configuration_are_read_only_disabled() {
    let root = tempfile::tempdir().unwrap();
    let before = fs::read_dir(root.path()).unwrap().count();
    let status = execute(root.path(), json!({"action":"status"})).unwrap();
    assert_eq!(status["enabled"], false);
    assert_eq!(status["status"], "disabled");
    let read = execute(root.path(), json!({"action":"read","task_id":"task-1"})).unwrap();
    assert_eq!(read["enabled"], false);
    assert_eq!(read["checkpoint"], Value::Null);
    assert_eq!(fs::read_dir(root.path()).unwrap().count(), before);
}

#[test]
fn mutation_without_configuration_does_not_initialize_the_project() {
    let root = tempfile::tempdir().unwrap();
    let before = fs::read_dir(root.path()).unwrap().count();
    let append = execute(
        root.path(),
        append_request("task-1", 1, "event-1", "completed"),
    )
    .unwrap_err();
    assert_eq!(code(&append), "handoff_disabled");
    let disable = execute(root.path(), json!({"action":"disable"})).unwrap();
    assert_eq!(disable["status"], "disabled");
    assert_eq!(fs::read_dir(root.path()).unwrap().count(), before);
}

#[test]
fn create_append_duplicate_and_cas_have_stable_shapes() {
    let root = tempfile::tempdir().unwrap();
    let created = execute(root.path(), create_request("task-1", "Example task")).unwrap();
    assert_eq!(created["status"], "saved");
    assert_eq!(created["revision"], 1);
    assert_eq!(
        execute(
            root.path(),
            append_request("task-1", 1, "event-1", "completed")
        )
        .unwrap()["revision"],
        2
    );
    let duplicate = execute(
        root.path(),
        append_request("task-1", 1, "event-1", "completed"),
    )
    .unwrap();
    assert_eq!(duplicate["status"], "duplicate");
    assert_eq!(duplicate["revision"], 2);
    let stale = execute(
        root.path(),
        append_request("task-1", 1, "event-2", "completed"),
    )
    .unwrap_err();
    assert_eq!(code(&stale), "revision_conflict");
    assert_eq!(stale["actual_revision"], 2);
    let read = execute(root.path(), json!({"action":"read","task_id":"task-1"})).unwrap();
    assert_eq!(read["revision"], 2);
    assert_eq!(read["checkpoint"]["events"].as_array().unwrap().len(), 1);
}

#[test]
fn runner_and_server_terminal_delivery_share_one_job_fact() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("task-1", "Example task")).unwrap();
    let runner = json!({
        "event_id":"runner-job-abc",
        "type":"job_terminal",
        "source":"runner",
        "job_id":"job-1",
        "job_update_seq":3,
        "status":"completed",
        "exit_code":0,
    });
    let saved = execute(
        root.path(),
        json!({"action":"append","task_id":"task-1","expected_revision":1,"event":runner}),
    )
    .unwrap();
    assert_eq!(saved["status"], "saved");

    let server = json!({
        "event_id":"job-terminal-abc",
        "type":"job_terminal",
        "source":"webcodex",
        "job_id":"job-1",
        "job_update_seq":3,
        "status":"completed",
        "exit_code":0,
        "observed_at":123,
    });
    let duplicate = execute(
        root.path(),
        json!({"action":"append","task_id":"task-1","expected_revision":1,"event":server}),
    )
    .unwrap();
    assert_eq!(duplicate["status"], "duplicate");
    assert_eq!(duplicate["event_id"], "job-terminal-abc");
    assert_eq!(duplicate["revision"], 2);

    let conflicting = json!({
        "event_id":"job-terminal-conflict",
        "type":"job_terminal",
        "source":"webcodex",
        "job_id":"job-1",
        "job_update_seq":3,
        "status":"failed",
        "exit_code":1,
    });
    execute(
        root.path(),
        json!({"action":"append","task_id":"task-1","expected_revision":2,"event":conflicting}),
    )
    .unwrap();
    let read = execute(root.path(), json!({"action":"read","task_id":"task-1"})).unwrap();
    assert_eq!(read["checkpoint"]["events"].as_array().unwrap().len(), 2);
    assert_eq!(read["checkpoint"]["events"][0]["source"], "runner");
    assert_eq!(read["checkpoint"]["events"][1]["status"], "failed");
}

#[test]
fn unknown_and_arbitrary_event_fields_are_preserved_or_rejected() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("task-1", "Example task")).unwrap();
    let unknown = execute(
        root.path(),
        json!({
            "action":"append",
            "task_id":"task-1",
            "expected_revision":1,
            "event": {"event_id":"event-unknown","type":"job_terminal","status":"unknown","unknown":true}
        }),
    )
    .unwrap();
    assert_eq!(unknown["revision"], 2);
    let status = execute(root.path(), json!({"action":"status"})).unwrap();
    assert_eq!(status["tasks"][0]["status"], "unknown");
    assert_eq!(status["tasks"][0]["unknown_count"], 1);
    let rejected = execute(
        root.path(),
        json!({
            "action":"append",
            "task_id":"task-1",
            "expected_revision":2,
            "event": {"event_id":"event-output","type":"job_terminal","output":{"stdout":"secret"}}
        }),
    )
    .unwrap_err();
    assert_eq!(code(&rejected), "event_field_not_allowed");
}

#[test]
fn old_markdown_is_never_overwritten() {
    let root = tempfile::tempdir().unwrap();
    let handoff = root.path().join("handoff");
    fs::create_dir(&handoff).unwrap();
    let old = "# User notes\n\nKeep this exact text.\n";
    fs::write(handoff.join("task-1.md"), old).unwrap();
    let created = execute(root.path(), create_request("task-1", "Example task")).unwrap();
    assert_eq!(created["markdown"], "preserved_unmanaged");
    execute(
        root.path(),
        append_request("task-1", 1, "event-1", "completed"),
    )
    .unwrap();
    assert_eq!(fs::read_to_string(handoff.join("task-1.md")).unwrap(), old);
}

#[test]
fn copied_project_identity_is_rejected() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("task-1", "Example task")).unwrap();
    let copy = tempfile::tempdir().unwrap();
    let copy_handoff = copy.path().join("handoff");
    fs::create_dir(&copy_handoff).unwrap();
    for name in ["index.json", "task-1.json", "task-1.md", ".lock"] {
        fs::copy(
            root.path().join("handoff").join(name),
            copy_handoff.join(name),
        )
        .unwrap();
    }
    let error = execute(copy.path(), json!({"action":"status"})).unwrap_err();
    assert_eq!(code(&error), "project_identity_mismatch");
}

#[test]
fn binding_is_explicit_and_status_only_reports_selection() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("task-1", "Example task")).unwrap();
    let binding = execute(
        root.path(),
        json!({"action":"bind","task_id":"task-1","client_id":"local:abc123"}),
    )
    .unwrap();
    assert_eq!(binding["status"], "bound");
    let status = execute(
        root.path(),
        json!({"action":"status","client_id":"local:abc123"}),
    )
    .unwrap();
    assert_eq!(status["bound_task_id"], "task-1");
}

#[test]
fn concurrent_appends_allow_one_cas_winner() {
    let root = Arc::new(tempfile::tempdir().unwrap());
    execute(root.path(), create_request("task-1", "Example task")).unwrap();
    let left = Arc::clone(&root);
    let right = Arc::clone(&root);
    let a = std::thread::spawn(move || {
        execute(
            left.path(),
            append_request("task-1", 1, "event-a", "completed"),
        )
    });
    let b = std::thread::spawn(move || {
        execute(
            right.path(),
            append_request("task-1", 1, "event-b", "completed"),
        )
    });
    let results = [a.join().unwrap(), b.join().unwrap()];
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| result
                .as_ref()
                .err()
                .is_some_and(|error| code(error) == "revision_conflict"))
            .count(),
        1
    );
}

#[test]
fn symlink_and_hardlink_targets_fail_closed() {
    use std::os::unix::fs::symlink;
    let root = tempfile::tempdir().unwrap();
    let external = tempfile::NamedTempFile::new().unwrap();
    let handoff = root.path().join("handoff");
    fs::create_dir(&handoff).unwrap();
    symlink(external.path(), handoff.join("index.json")).unwrap();
    let error = execute(root.path(), json!({"action":"status"})).unwrap_err();
    assert_eq!(code(&error), "unsafe_path");

    let second = tempfile::tempdir().unwrap();
    execute(second.path(), create_request("task-1", "Example task")).unwrap();
    fs::hard_link(
        second.path().join("handoff").join("task-1.json"),
        second.path().join("handoff").join("task-copy.json"),
    )
    .unwrap();
    let error = execute(
        second.path(),
        append_request("task-1", 1, "event-1", "completed"),
    )
    .unwrap_err();
    assert_eq!(code(&error), "unsafe_path");
}

#[test]
fn event_capacity_archives_history_and_preserves_binding_unknown_and_dedup() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("task-1", "Example task")).unwrap();
    execute(
        root.path(),
        json!({"action":"bind","task_id":"task-1","client_id":"local:one"}),
    )
    .unwrap();
    for i in 0..(MAX_EVENT_COUNT * 2 + 1) {
        execute(
            root.path(),
            append_request(
                "task-1",
                i as u64 + 1,
                &format!("event-{i}"),
                if i == 0 { "unknown" } else { "completed" },
            ),
        )
        .unwrap();
    }
    let saved = execute(root.path(), json!({"action":"read","task_id":"task-1"})).unwrap();
    assert_eq!(saved["event_count"], 257);
    assert_eq!(saved["history"]["archived_events"], 256);
    assert_eq!(saved["checkpoint"]["unknown_count"], 1);
    assert_eq!(saved["checkpoint"]["events"].as_array().unwrap().len(), 1);
    let files = saved["history"]["files"].as_array().unwrap();
    assert_eq!(files.len(), 2);
    let history: Vec<Value> =
        serde_json::from_slice(&fs::read(root.path().join(files[0].as_str().unwrap())).unwrap())
            .unwrap();
    assert_eq!(history[0]["status"], "unknown");
    assert_eq!(history.len(), 128);
    let duplicate = execute(
        root.path(),
        append_request("task-1", 1, "event-0", "unknown"),
    )
    .unwrap();
    assert_eq!(duplicate["status"], "duplicate");
    assert_eq!(duplicate["revision"], 258);
    let status = execute(
        root.path(),
        json!({"action":"status","client_id":"local:one"}),
    )
    .unwrap();
    assert_eq!(status["bound_task_id"], "task-1");
    assert_eq!(status["tasks"][0]["event_count"], 257);
    execute(root.path(), json!({"action":"append","task_id":"task-1","expected_revision":258,
        "event":{"event_id":"stage-end","type":"stage_finished","summary":"Next: real phone verification"}})).unwrap();
    // Corrupt history must never be treated as absent or silently repaired.
    fs::write(root.path().join(files[0].as_str().unwrap()), b"[]").unwrap();
    let error = execute(root.path(), json!({"action":"read","task_id":"task-1"})).unwrap_err();
    assert_eq!(code(&error), "archive_corrupt");
}

#[test]
fn archive_retry_after_segment_commit_preserves_human_notes() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("retry", "Retry")).unwrap();
    for i in 0..MAX_EVENT_COUNT {
        execute(
            root.path(),
            append_request("retry", i as u64 + 1, &format!("e{i}"), "completed"),
        )
        .unwrap();
    }
    let project = open_project_root(root.path()).unwrap();
    with_write_lock(&project, |dir| {
        let mut task = load_task(dir, &project.identity, "retry")?;
        task.events.push(event("after", "completed"));
        let (name, bytes) = plan_archive(&mut task)?.unwrap();
        atomic_write(dir, &name, &bytes, false)?;
        Ok(())
    })
    .unwrap();
    let md = root.path().join("handoff/retry.md");
    let old = fs::read_to_string(&md).unwrap();
    fs::write(&md, format!("{old}\nKeep my note.\n")).unwrap();
    execute(
        root.path(),
        append_request("retry", 129, "after", "completed"),
    )
    .unwrap();
    let read = execute(root.path(), json!({"action":"read","task_id":"retry"})).unwrap();
    assert_eq!(read["event_count"], 129);
    assert!(fs::read_to_string(md).unwrap().contains("Keep my note."));
}

#[test]
fn replicated_terminal_dedup_keeps_all_new_evidence_and_both_arrival_orders() {
    let fact = json!({"event_id":"runner","source":"runner","type":"job_terminal","job_id":"j","job_update_seq":3,"status":"completed","exit_code":0});
    let mut server = fact.clone();
    server["event_id"] = json!("server");
    server["source"] = json!("webcodex");
    server["observed_at"] = json!(42);
    for reverse in [false, true] {
        let root = tempfile::tempdir().unwrap();
        execute(root.path(), create_request("t", "T")).unwrap();
        let (first, second) = if reverse {
            (&server, &fact)
        } else {
            (&fact, &server)
        };
        execute(
            root.path(),
            json!({"action":"append","task_id":"t","expected_revision":1,"event":first}),
        )
        .unwrap();
        assert_eq!(
            execute(
                root.path(),
                json!({"action":"append","task_id":"t","expected_revision":1,"event":second})
            )
            .unwrap()["status"],
            "duplicate"
        );
    }
    for (field, value) in [
        ("summary", json!("new evidence")),
        ("outcome", json!("unknown")),
        ("task_status", json!("blocked")),
        ("paths", json!(["src/a.rs"])),
        ("exit_code", json!(7)),
    ] {
        let root = tempfile::tempdir().unwrap();
        execute(root.path(), create_request("t", "T")).unwrap();
        execute(
            root.path(),
            json!({"action":"append","task_id":"t","expected_revision":1,"event":fact}),
        )
        .unwrap();
        let mut incoming = server.clone();
        incoming[field] = value.clone();
        assert_eq!(
            execute(
                root.path(),
                json!({"action":"append","task_id":"t","expected_revision":2,"event":incoming})
            )
            .unwrap()["status"],
            "saved"
        );
        let read = execute(root.path(), json!({"action":"read","task_id":"t"})).unwrap();
        assert_eq!(read["checkpoint"]["events"][1][field], value);
        if field == "outcome" {
            assert_eq!(read["checkpoint"]["unknown_count"], 1);
        }
        if field == "task_status" {
            assert_eq!(read["checkpoint"]["status"], "blocked");
        }
    }
    let mut note = server.clone();
    note["source"] = json!("gpt");
    assert!(!same_terminal_job_fact(&fact, &note));
}

#[test]
fn stale_index_is_readable_and_append_repairs_its_projection() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("task-1", "Example task")).unwrap();

    // Model a crash after the task file was durably replaced but before the
    // index projection was replaced.  The task remains valid and is the
    // source of truth for its CAS revision.
    let task_path = root.path().join("handoff").join("task-1.json");
    let mut task: Value = serde_json::from_slice(&fs::read(&task_path).unwrap()).unwrap();
    task["revision"] = json!(2);
    task["updated_at"] = json!(2);
    fs::write(&task_path, serde_json::to_vec_pretty(&task).unwrap()).unwrap();

    let status = execute(root.path(), json!({"action":"status"})).unwrap();
    assert_eq!(status["integrity"], "index_stale");
    assert_eq!(status["tasks"][0]["revision"], 2);
    let read = execute(root.path(), json!({"action":"read","task_id":"task-1"})).unwrap();
    assert_eq!(read["integrity"], "index_stale");

    let saved = execute(
        root.path(),
        append_request("task-1", 2, "event-repair", "completed"),
    )
    .unwrap();
    assert_eq!(saved["revision"], 3);
    let repaired = execute(root.path(), json!({"action":"status"})).unwrap();
    assert!(repaired.get("integrity").is_none());
    assert_eq!(repaired["tasks"][0]["revision"], 3);
}

#[test]
fn terminal_projection_survives_late_running_and_lower_sequence() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("ordered", "Ordered")).unwrap();
    for (revision, id, kind, status, seq, exit) in [
        (1, "end", "job_terminal", "failed", 3, Some(7)),
        (2, "late", "job_started", "running", 2, None),
        (3, "old", "job_terminal", "completed", 1, Some(0)),
    ] {
        let mut fact = json!({"event_id":id,"type":kind,"source":"runner","job_id":"job-one","status":status,"job_update_seq":seq});
        if let Some(code) = exit {
            fact["exit_code"] = code.into();
        }
        execute(root.path(), json!({"action":"append","task_id":"ordered","expected_revision":revision,"event":fact})).unwrap();
    }
    let saved = execute(root.path(), json!({"action":"read","task_id":"ordered"})).unwrap();
    assert_eq!(saved["jobs"][0]["status"], "failed");
    assert_eq!(saved["jobs"][0]["exit_code"], 7);
    assert_eq!(saved["jobs"][0]["job_update_seq"], 3);
    assert_eq!(saved["checkpoint"]["events"].as_array().unwrap().len(), 3);
}

#[test]
fn archive_byte_rollover_and_history_paths_fail_closed() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("bytes", "Bytes")).unwrap();
    for i in 0..80 {
        let mut request = append_request("bytes", i + 1, &format!("e{i}"), "completed");
        request["event"]["summary"] = json!("x".repeat(4000));
        execute(root.path(), request).unwrap();
    }
    let read = execute(root.path(), json!({"action":"read","task_id":"bytes"})).unwrap();
    assert!(read["history"]["archived_events"].as_u64().unwrap() > 0);
    assert_eq!(read["event_count"], 80);
    let file = root
        .path()
        .join(read["history"]["files"][0].as_str().unwrap());
    let bytes = fs::read(&file).unwrap();
    fs::remove_file(&file).unwrap();
    let missing = execute(root.path(), json!({"action":"read","task_id":"bytes"})).unwrap_err();
    assert_eq!(code(&missing), "archive_missing");
    let external = root.path().join("outside");
    fs::write(&external, bytes).unwrap();
    std::os::unix::fs::symlink(&external, &file).unwrap();
    let linked = execute(root.path(), json!({"action":"read","task_id":"bytes"})).unwrap_err();
    assert_eq!(code(&linked), "unsafe_path");
}

#[test]
fn archived_bytes_count_towards_project_budget() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("budget", "Budget")).unwrap();
    let project = open_project_root(root.path()).unwrap();
    with_write_lock(&project, |dir| {
        let index = load_index(dir, &project.identity)?.unwrap();
        let mut task = load_task(dir, &project.identity, "budget")?;
        // A planned segment is counted even before it exists on disk.
        for i in 0..9 {
            let hash = format!("{i:064x}");
            task.archives.push(EventArchive {
                file: format!("budget.events-{hash}.json"),
                sha256: hash,
                event_count: 1,
                bytes: MAX_TASK_BYTES,
            });
            task.events.push(event(&format!("e{i}"), "completed"));
        }
        let bytes = serialize_task(&task)?;
        let failure = check_total_capacity(dir, &index, "budget", &bytes, None).unwrap_err();
        assert_eq!(code(&failure), "capacity_exceeded");
        Ok(())
    })
    .unwrap();
}

#[test]
fn acknowledged_alias_rejects_changed_facts_after_reload_and_archive() {
    for reverse in [false, true] {
        let root = tempfile::tempdir().unwrap();
        execute(root.path(), create_request("aliases", "Aliases")).unwrap();
        let runner = json!({"event_id":"runner","source":"runner","type":"job_terminal","job_id":"j","job_update_seq":3,"status":"completed","exit_code":0});
        let mut server = runner.clone();
        server["event_id"] = json!("server");
        server["source"] = json!("webcodex");
        server["observed_at"] = json!(42);
        let (first, alias) = if reverse {
            (&server, &runner)
        } else {
            (&runner, &server)
        };
        execute(
            root.path(),
            json!({"action":"append","task_id":"aliases","expected_revision":1,"event":first}),
        )
        .unwrap();
        let request =
            json!({"action":"append","task_id":"aliases","expected_revision":1,"event":alias});
        let saved = execute(root.path(), request.clone()).unwrap();
        assert_eq!(saved["status"], "duplicate");
        assert_eq!(saved["revision"], 2);
        assert_eq!(
            execute(root.path(), request.clone()).unwrap()["status"],
            "duplicate"
        );
        // Move the original fact into an archive; alias identity must survive.
        for i in 0..128 {
            execute(
                root.path(),
                append_request("aliases", i + 2, &format!("other-{i}"), "completed"),
            )
            .unwrap();
        }
        let read = execute(root.path(), json!({"action":"read","task_id":"aliases"})).unwrap();
        assert_eq!(read["event_count"], 129);
        assert_eq!(read["history"]["archived_events"], 128);
        assert_eq!(
            execute(root.path(), request.clone()).unwrap()["status"],
            "duplicate"
        );
        let mut changed = request;
        changed["expected_revision"] = json!(130);
        changed["event"]["status"] = json!("failed");
        changed["event"]["exit_code"] = json!(7);
        assert_eq!(
            code(&execute(root.path(), changed.clone()).unwrap_err()),
            "event_id_conflict"
        );
        // New identity with new evidence remains valid, not over-deduplicated.
        changed["event"]["event_id"] = json!("new-evidence");
        assert_eq!(execute(root.path(), changed).unwrap()["status"], "saved");
    }
}

#[test]
fn alias_capacity_failure_does_not_acknowledge_or_change_task() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("full", "Full")).unwrap();
    let fact = json!({"event_id":"runner","source":"runner","type":"job_terminal","job_id":"j","job_update_seq":3,"status":"completed","exit_code":0});
    execute(
        root.path(),
        json!({"action":"append","task_id":"full","expected_revision":1,"event":fact}),
    )
    .unwrap();
    let project = open_project_root(root.path()).unwrap();
    with_write_lock(&project, |dir| {
        let mut task = load_task(dir, &project.identity, "full")?;
        for i in 0..4000 {
            let id = format!("x{i:0127}");
            task.event_aliases.insert(id.clone(), "a".repeat(64));
            if serialize_task(&task).is_err() {
                task.event_aliases.remove(&id);
                break;
            }
        }
        atomic_write(dir, "full.json", &serialize_task(&task)?, true)
    })
    .unwrap();
    let before = fs::read(root.path().join("handoff/full.json")).unwrap();
    let mut alias = fact;
    alias["event_id"] = json!("z".repeat(128));
    alias["source"] = json!("webcodex");
    let error = execute(
        root.path(),
        json!({"action":"append","task_id":"full","expected_revision":2,"event":alias}),
    )
    .unwrap_err();
    assert_eq!(code(&error), "capacity_exceeded");
    assert_eq!(
        before,
        fs::read(root.path().join("handoff/full.json")).unwrap()
    );
}

#[test]
fn status_reports_capacity_usage_without_mutating_history() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("usage", "Usage")).unwrap();
    let file = root.path().join("handoff/usage.json");
    let before = fs::read(&file).unwrap();
    let status = execute(root.path(), json!({"action":"status"})).unwrap();
    assert_eq!(status["usage"]["tasks"], 1);
    assert!(status["usage"]["bytes"].as_u64().unwrap() > before.len() as u64);
    assert_eq!(status["usage"]["near_limit"], false);
    assert_eq!(fs::read(&file).unwrap(), before);
}

#[test]
fn status_warns_before_task_limit_without_removing_tasks() {
    let root = tempfile::tempdir().unwrap();
    for i in 0..52 {
        execute(
            root.path(),
            create_request(&format!("task-{i}"), "Capacity fixture"),
        )
        .unwrap();
    }
    let status = execute(root.path(), json!({"action":"status"})).unwrap();
    assert_eq!(status["usage"]["tasks"], 52);
    assert_eq!(status["usage"]["near_limit"], true);
    assert_eq!(status["tasks"].as_array().unwrap().len(), 52);
}

#[test]
fn archive_preserves_history_frees_slot_and_rejects_old_session() {
    let root = tempfile::tempdir().unwrap();
    let mut create = create_request("done", "Done");
    create["client_id"] = json!("local:old");
    execute(root.path(), create).unwrap();
    execute(root.path(), json!({"action":"append","task_id":"done","expected_revision":1,
        "event":{"event_id":"finish","type":"task_completed","source":"local_codex","status":"completed"}})).unwrap();
    let json_path = root.path().join("handoff/done.json");
    let md_path = root.path().join("handoff/done.md");
    let original = fs::read(&json_path).unwrap();
    let markdown = fs::read(&md_path).unwrap();
    for i in 1..MAX_TASK_COUNT {
        execute(root.path(), create_request(&format!("task-{i}"), "Active")).unwrap();
    }
    assert!(execute(root.path(), create_request("overflow", "Full")).is_err());
    let request = json!({"action":"archive","task_id":"done","expected_revision":2});
    assert_eq!(
        execute(root.path(), request.clone()).unwrap()["duplicate"],
        false
    );
    assert_eq!(execute(root.path(), request).unwrap()["duplicate"], true);
    assert_eq!(fs::read(json_path).unwrap(), original);
    assert_eq!(fs::read(md_path).unwrap(), markdown);
    let read = execute(root.path(), json!({"action":"read","task_id":"done"})).unwrap();
    assert_eq!(read["archived"], true);
    assert_eq!(read["event_count"], 1);
    let status = execute(
        root.path(),
        json!({"action":"status","client_id":"local:old"}),
    )
    .unwrap();
    assert_eq!(status["usage"]["tasks"], MAX_TASK_COUNT - 1);
    assert_eq!(status["bound_task_id"], Value::Null);
    execute(root.path(), create_request("new", "New")).unwrap();
    assert_eq!(
        code(
            &execute(
                root.path(),
                json!({"action":"bind","task_id":"new","client_id":"local:old"})
            )
            .unwrap_err()
        ),
        "task_archived"
    );
    assert!(execute(root.path(), create_request("done", "Reuse")).is_err());
    assert!(execute(root.path(), append_request("done", 2, "late", "completed")).is_err());
}

#[test]
fn archive_rejects_unknown_active_and_server_uncoordinated_tasks() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("task", "Task")).unwrap();
    let mut archive = json!({"action":"archive","task_id":"task","expected_revision":1});
    assert_eq!(
        code(&execute(root.path(), archive.clone()).unwrap_err()),
        "task_unresolved"
    );
    execute(
        root.path(),
        json!({"action":"append","task_id":"task","expected_revision":1,
        "event":{"event_id":"finish","type":"task_completed","source":"gpt","status":"completed"}}),
    )
    .unwrap();
    archive["expected_revision"] = json!(2);
    execute(
        root.path(),
        json!({"action":"bind","task_id":"task","client_id":"webcodex:old"}),
    )
    .unwrap();
    assert_eq!(
        code(&execute(root.path(), archive.clone()).unwrap_err()),
        "server_retirement_required"
    );
    execute_from_runner(root.path(), archive).unwrap();
    execute(root.path(), create_request("unknown", "Unknown")).unwrap();
    execute(
        root.path(),
        append_request("unknown", 1, "uncertain", "unknown"),
    )
    .unwrap();
    assert!(execute_from_runner(
        root.path(),
        json!({"action":"archive","task_id":"unknown","expected_revision":2})
    )
    .is_err());
}

#[cfg(target_os = "macos")]
#[test]
fn legacy_device_repair_preserves_bytes_and_refuses_stale_or_remote_requests() {
    let root = tempfile::tempdir().unwrap();
    execute(root.path(), create_request("legacy", "旧任务")).unwrap();
    fs::remove_file(root.path().join("handoff/.volume-anchor.json")).unwrap();
    let project = open_project_root(root.path()).unwrap();
    let mut old = project.identity.clone();
    old.device += 1;
    let mut hash = Sha256::new();
    hash.update(old.canonical_root.as_bytes());
    hash.update(b"\0");
    hash.update(old.device.to_le_bytes());
    hash.update(old.inode.to_le_bytes());
    old.root_fingerprint = format!("{:x}", hash.finalize());
    for file in ["index.json", "legacy.json"] {
        let path = root.path().join("handoff").join(file);
        let mut value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        value["project_identity"] = serde_json::to_value(&old).unwrap();
        fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    }
    let paths: Vec<_> = ["index.json", "legacy.json", "legacy.md"]
        .iter()
        .map(|name| root.path().join("handoff").join(name))
        .collect();
    let before: Vec<_> = paths.iter().map(|p| fs::read(p).unwrap()).collect();
    assert_eq!(
        execute(root.path(), json!({"action":"read","task_id":"legacy"})).unwrap_err()["code"],
        "project_identity_mismatch"
    );
    let req = json!({"action":"anchor_identity","expected_index_sha256":format!("{:x}",Sha256::digest(&before[0])),"confirm":true});
    assert_eq!(
        execute_from_runner(root.path(), req.clone()).unwrap_err()["code"],
        "invalid_action"
    );
    let mut stale = req.clone();
    stale["expected_index_sha256"] = "bad".into();
    assert_eq!(
        execute(root.path(), stale).unwrap_err()["code"],
        "revision_conflict"
    );
    let mut preview = req.clone();
    preview["confirm"] = false.into();
    assert_eq!(execute(root.path(), preview).unwrap()["status"], "reviewed");
    assert!(!root.path().join("handoff/.volume-anchor.json").exists());
    assert_eq!(execute(root.path(), req).unwrap()["status"], "anchored");
    assert_eq!(
        execute(root.path(), json!({"action":"read","task_id":"legacy"})).unwrap()["status"],
        "ready"
    );
    assert_eq!(
        before,
        paths
            .iter()
            .map(|p| fs::read(p).unwrap())
            .collect::<Vec<_>>()
    );
    // A copied anchor does not grant continuity to another directory.
    let other = tempfile::tempdir().unwrap();
    fs::create_dir(other.path().join("handoff")).unwrap();
    fs::copy(
        root.path().join("handoff/.volume-anchor.json"),
        other.path().join("handoff/.volume-anchor.json"),
    )
    .unwrap();
    assert_eq!(
        execute(other.path(), json!({"action":"status"})).unwrap_err()["code"],
        "project_identity_mismatch"
    );
    // Even the same path/inode is rejected when the stable volume differs.
    let path = root.path().join("handoff/.volume-anchor.json");
    let mut value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    value["volume_uuid"] = "00000000000000000000000000000000".into();
    fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert_eq!(
        execute(root.path(), json!({"action":"status"})).unwrap_err()["code"],
        "project_identity_mismatch"
    );
}
