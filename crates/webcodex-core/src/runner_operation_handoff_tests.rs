use super::*;

fn payload(action: &str) -> RunnerFilePayload {
    RunnerFilePayload {
        cwd: Some("/project".into()),
        path: ".".into(),
        content: Some(serde_json::json!({"action":action}).to_string()),
        max_bytes: None,
        expected_sha256: None,
        expected_prefix: None,
        start_line: None,
        end_line: None,
        create_dirs: false,
    }
}

#[test]
fn handoff_read_cannot_carry_a_mutation() {
    for action in ["create", "append", "bind", "disable", "archive", "unknown"] {
        assert!(validate_file_payload("file_handoff_read", &payload(action)).is_err());
    }
    for action in ["status", "read"] {
        assert!(validate_file_payload("file_handoff_read", &payload(action)).is_ok());
        assert!(validate_file_payload("file_handoff_write", &payload(action)).is_err());
    }
}

#[test]
fn handoff_requires_exact_project_root_and_bounded_request() {
    let mut p = payload("append");
    assert!(validate_file_payload("file_handoff_write", &p).is_ok());
    p.path = "../other".into();
    assert!(validate_file_payload("file_handoff_write", &p).is_err());
    p.path = ".".into();
    p.cwd = Some("relative".into());
    assert!(validate_file_payload("file_handoff_write", &p).is_err());
    p.cwd = Some("/project".into());
    p.content = Some("x".repeat(128 * 1024 + 1));
    assert!(validate_file_payload("file_handoff_write", &p).is_err());
}
