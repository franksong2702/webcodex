use super::*;
use serde_json::json;

fn binding(session: &str) -> HandoffBinding {
    HandoffBinding {
        session_id: session.into(),
        project_id: "agent:runner:project".into(),
        client_id: "runner".into(),
        project_path: "/fixture/project".into(),
        task_id: "task-a".into(),
        root_fingerprint: "a".repeat(64),
    }
}

#[test]
fn handoff_outbox_survives_reopen_and_deduplicates_without_retargeting() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("test.db");
    let db = Database::open(&path).unwrap();
    db.handoff_bind(&binding("s1")).unwrap();
    let event =
        json!({"event_id":"e1","type":"tool_finished","source":"webcodex","status":"unknown"});
    db.handoff_enqueue("s1", &event, 100).unwrap();
    db.handoff_enqueue("s1", &event, 101).unwrap();
    assert_eq!(db.handoff_pending("s1").unwrap().len(), 1);
    let mut changed = event.clone();
    changed["status"] = json!("completed");
    assert!(db.handoff_enqueue("s1", &changed, 102).is_err());
    let mut target = binding("s1");
    target.task_id = "task-b".into();
    assert!(db.handoff_bind(&target).is_err());
    drop(db);
    let db = Database::open(&path).unwrap();
    assert_eq!(db.handoff_pending("s1").unwrap()[0].event, event);
    assert_eq!(db.handoff_binding("s1").unwrap().unwrap(), binding("s1"));
    db.handoff_ack("other-session", "e1").unwrap();
    assert_eq!(db.handoff_pending("s1").unwrap().len(), 1);
    db.handoff_ack("s1", "e1").unwrap();
    assert!(db.handoff_pending("s1").unwrap().is_empty());
}

#[test]
fn handoff_outbox_rejects_raw_content_and_unbound_sources() {
    let tmp = tempfile::tempdir().unwrap();
    let db = Database::open(&tmp.path().join("test.db")).unwrap();
    let event = json!({"event_id":"e1","type":"tool_finished"});
    assert!(db.handoff_enqueue("missing", &event, 100).is_err());
    db.handoff_bind(&binding("s1")).unwrap();
    for field in [
        "command",
        "stdout",
        "stderr",
        "env",
        "transcript",
        "arguments",
    ] {
        let mut bad = event.clone();
        bad[field] = json!("private-content");
        assert!(db.handoff_enqueue("s1", &bad, 100).is_err());
    }
    let mut nested = event.clone();
    nested["status"] = json!({"raw":"private-content"});
    assert!(db.handoff_enqueue("s1", &nested, 100).is_err());
    assert!(db.handoff_pending("s1").unwrap().is_empty());
}

#[test]
fn handoff_fresh_session_can_reconcile_same_task_without_crossing_target_identity() {
    let tmp = tempfile::tempdir().unwrap();
    let db = Database::open(&tmp.path().join("test.db")).unwrap();
    db.handoff_bind(&binding("old-session")).unwrap();
    db.handoff_enqueue("old-session", &json!({"event_id":"pending-old","type":"job_terminal","job_id":"same-job","status":"failed"}),100).unwrap();
    let receiver = binding("new-session");
    db.handoff_bind(&receiver).unwrap();
    let pending = db.handoff_pending_for_task(&receiver).unwrap();
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].session_id, "old-session");
    let mut other = receiver.clone();
    other.task_id = "different-task".into();
    assert!(db.handoff_pending_for_task(&other).unwrap().is_empty());
    other = receiver.clone();
    other.root_fingerprint = "b".repeat(64);
    assert!(db.handoff_pending_for_task(&other).unwrap().is_empty());
    other = receiver.clone();
    other.project_id = "agent:other:project".into();
    assert!(db.handoff_pending_for_task(&other).unwrap().is_empty());
}

#[test]
fn retirement_preserves_late_facts_and_immutable_identity_across_reopen() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("retirement.db");
    let db = Database::open(&path).unwrap();
    let b = binding("old");
    db.handoff_bind(&b).unwrap();
    let e =
        json!({"event_id":"late","type":"tool_finished","source":"webcodex","status":"unknown"});
    db.handoff_enqueue("old", &e, 1).unwrap();
    assert!(db.handoff_retire(&b, false).is_err());
    db.handoff_ack("old", "late").unwrap();
    db.handoff_retire(&b, false).unwrap();
    assert!(db.handoff_bind(&binding("new-same-task")).is_err());
    db.handoff_enqueue("old", &e, 2).unwrap();
    assert!(db.handoff_retire(&b, true).is_err());
    assert_eq!(db.handoff_pending("old").unwrap().len(), 1);
    db.handoff_ack("old", "late").unwrap();
    db.handoff_retire(&b, true).unwrap();
    drop(db);
    let db = Database::open(&path).unwrap();
    assert!(db.handoff_retirement_started(&b).unwrap());
    assert_eq!(db.handoff_binding("old").unwrap().unwrap(), b);
    let mut other = b.clone();
    other.task_id = "other".into();
    assert!(db.handoff_bind(&other).is_err());
    other.session_id = "fresh".into();
    db.handoff_bind(&other).unwrap();
    db.handoff_enqueue("old", &e, 3).unwrap();
    assert_eq!(db.handoff_pending("old").unwrap()[0].event, e);
    assert_eq!(
        db.handoff_source_status(
            &b.project_id,
            &b.project_path,
            Some(&b.task_id),
            Some(&b.root_fingerprint)
        )
        .unwrap()["status"],
        "pending"
    );
}

#[test]
fn retiring_bindings_releases_active_capacity_without_deleting_history() {
    let tmp = tempfile::tempdir().unwrap();
    let db = Database::open(&tmp.path().join("capacity.db")).unwrap();
    for i in 0..1024 {
        db.handoff_bind(&binding(&format!("s{i}"))).unwrap();
    }
    let mut fresh = binding("fresh");
    fresh.task_id = "new-task".into();
    assert!(db.handoff_bind(&fresh).is_err());
    db.handoff_retire(&binding("s0"), false).unwrap();
    // Preparing never frees quota; only confirmed archival does.
    assert!(db.handoff_bind(&fresh).is_err());
    db.handoff_retire(&binding("s0"), true).unwrap();
    db.handoff_bind(&fresh).unwrap();
    assert_eq!(
        db.handoff_binding("s1023").unwrap().unwrap(),
        binding("s1023")
    );
    assert!(db.handoff_bind(&binding("s0")).is_err());
}
