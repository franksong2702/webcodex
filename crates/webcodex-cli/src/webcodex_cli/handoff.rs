//! Local checkpoint adapter. Reads one bounded JSON request; never starts a
//! model, network client, background process, or alters hooks configuration.
use serde_json::{json, Value};
use std::io::Read;
use std::path::PathBuf;

const MAX_INPUT: u64 = 128 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Options {
    pub project: PathBuf,
}

pub(crate) fn parse(args: &[String]) -> Result<Options, String> {
    if args.len() != 3 || args[0] != "--project" || args[2] != "--request-stdin" {
        return Err(
            "Usage: webcodex handoff --project <absolute-directory> --request-stdin".into(),
        );
    }
    let project = PathBuf::from(&args[1]);
    if !project.is_absolute() {
        return Err("handoff requires an explicit absolute project directory".into());
    }
    Ok(Options { project })
}

pub(crate) fn run(options: Options, input: impl Read) -> (i32, Value) {
    let mut bytes = Vec::new();
    if input.take(MAX_INPUT + 1).read_to_end(&mut bytes).is_err() {
        return failed("input_unavailable");
    }
    if bytes.len() as u64 > MAX_INPUT {
        return failed("input_too_large");
    }
    let request: Value = match serde_json::from_slice(&bytes) {
        Ok(value) => value,
        Err(_) => return failed("invalid_json"),
    };
    match webcodex_workspace::handoff_checkpoint::execute(&options.project, request) {
        Ok(output) => (0, json!({"success":true,"output":output})),
        Err(error) => (1, json!({"success":false,"error":error})),
    }
}

fn failed(code: &str) -> (i32, Value) {
    (1, json!({"success":false,"error":{"code":code}}))
}

#[cfg(test)]
#[path = "tests/handoff.rs"]
mod tests;
