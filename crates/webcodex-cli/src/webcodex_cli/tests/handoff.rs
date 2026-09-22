use super::*;

#[test]
fn handoff_requires_explicit_absolute_project_and_stdin() {
    assert!(parse(&[
        "--project".into(),
        "relative".into(),
        "--request-stdin".into()
    ])
    .is_err());
    assert!(parse(&[
        "--project".into(),
        "/tmp/fixture".into(),
        "--request-stdin".into()
    ])
    .is_ok());
    assert!(parse(&[
        "--project".into(),
        "/tmp/fixture".into(),
        "--request-stdin".into(),
        "ignored".into()
    ])
    .is_err());
}

#[test]
fn handoff_rejects_malformed_or_oversized_input_before_any_write() {
    let root = tempfile::tempdir().unwrap();
    let opts = Options {
        project: root.path().to_path_buf(),
    };
    let (code, value) = run(opts.clone(), &b"not JSON"[..]);
    assert_eq!(code, 1);
    assert_eq!(value["error"]["code"], "invalid_json");
    let oversized = vec![b' '; MAX_INPUT as usize + 1];
    assert_eq!(
        run(opts, oversized.as_slice()).1["error"]["code"],
        "input_too_large"
    );
    assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 0);
}
