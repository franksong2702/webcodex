//! Stable macOS volume identity, preserving legacy task/receipt fingerprints.
//! This is directory provenance, never execution authorization.
use super::*;
const NAME: &str = ".volume-anchor.json";

#[derive(serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Anchor {
    version: u32,
    volume_uuid: String,
    identity: ProjectIdentity,
}

#[cfg(target_os = "macos")]
fn volume(directory: &fs::File) -> Result<String, Value> {
    use std::os::fd::AsRawFd;
    let mut attrs = libc::attrlist {
        bitmapcount: 5,
        reserved: 0,
        commonattr: 0,
        volattr: 0x8004_0000, // ATTR_VOL_INFO | ATTR_VOL_UUID
        dirattr: 0,
        fileattr: 0,
        forkattr: 0,
    };
    let mut bytes = [0u8; 20];
    let rc = unsafe {
        libc::fgetattrlist(
            directory.as_raw_fd(),
            (&mut attrs as *mut libc::attrlist).cast(),
            bytes.as_mut_ptr().cast(),
            bytes.len(),
            0,
        )
    };
    if rc != 0
        || u32::from_ne_bytes(bytes[..4].try_into().unwrap()) != 20
        || bytes[4..].iter().all(|b| *b == 0)
    {
        return Err(error(
            "volume_identity_unavailable",
            "stable volume identity is unavailable",
        ));
    }
    Ok(bytes[4..].iter().map(|b| format!("{b:02x}")).collect())
}

#[cfg(not(target_os = "macos"))]
fn volume(_: &fs::File) -> Result<String, Value> {
    Err(error(
        "unsupported_platform",
        "volume anchoring is supported on macOS only",
    ))
}

fn validate(anchor: &Anchor, current: &ProjectIdentity, uuid: &str) -> Result<(), Value> {
    let saved = &anchor.identity;
    let mut hash = Sha256::new();
    hash.update(saved.canonical_root.as_bytes());
    hash.update(b"\0");
    hash.update(saved.device.to_le_bytes());
    hash.update(saved.inode.to_le_bytes());
    if anchor.version != 1
        || anchor.volume_uuid != uuid
        || saved.canonical_root != current.canonical_root
        || saved.inode != current.inode
        || saved.root_fingerprint != format!("{:x}", hash.finalize())
    {
        return Err(error(
            "project_identity_mismatch",
            "volume anchor belongs to another directory",
        ));
    }
    Ok(())
}

pub(super) fn resolve(root: &mut ProjectRoot) -> Result<(), Value> {
    let Some(dir) = open_handoff_dir(root)? else {
        return Ok(());
    };
    let Some(bytes) = read_file_bounded(&dir, NAME, 4096, "capacity_exceeded")? else {
        return Ok(());
    };
    let anchor: Anchor = serde_json::from_slice(&bytes)
        .map_err(|_| error("invalid_volume_anchor", "volume anchor is malformed"))?;
    validate(&anchor, &root.identity, &volume(&root.directory)?)?;
    root.identity = anchor.identity;
    Ok(())
}

pub(super) fn create(root: &ProjectRoot, dir: &HandoffDir) -> Result<(), Value> {
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (root, dir);
        return Ok(());
    }
    #[cfg(target_os = "macos")]
    {
        let uuid = volume(&root.directory)?;
        if let Some(bytes) = read_file_bounded(dir, NAME, 4096, "capacity_exceeded")? {
            let anchor: Anchor = serde_json::from_slice(&bytes)
                .map_err(|_| error("invalid_volume_anchor", "volume anchor is malformed"))?;
            return validate(&anchor, &root.identity, &uuid);
        }
        let anchor = Anchor {
            version: 1,
            volume_uuid: uuid,
            identity: root.identity.clone(),
        };
        let bytes = serde_json::to_vec(&anchor).map_err(|_| {
            error(
                "invalid_volume_anchor",
                "volume anchor cannot be serialized",
            )
        })?;
        atomic_write_checked(dir, NAME, &bytes, false, Some(None))
    }
}

/// Explicit local operator repair, not available through the Runner/MCP.
/// Existing JSON/Markdown/archives and their fingerprints are never rewritten.
pub(super) fn repair(root: &Path, request: Value) -> Result<Value, Value> {
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Request {
        action: String,
        expected_index_sha256: String,
        confirm: bool,
    }
    let req: Request = serde_json::from_value(request).map_err(|_| {
        error(
            "invalid_request",
            "exact index digest and explicit confirmation are required",
        )
    })?;
    if req.action != "anchor_identity" {
        return Err(error("invalid_action", "invalid anchor action"));
    }
    let project = open_project_root(root)?;
    let uuid = volume(&project.directory)?;
    with_existing_write_lock(&project, |dir| {
        let bytes = read_file_bounded(dir, INDEX_FILE_NAME, MAX_INDEX_BYTES, "capacity_exceeded")?
            .ok_or_else(|| error("missing_index", "existing managed index is required"))?;
        if format!("{:x}", Sha256::digest(&bytes)) != req.expected_index_sha256 {
            return Err(error(
                "revision_conflict",
                "index changed since operator review",
            ));
        }
        let index: IndexFile = serde_json::from_slice(&bytes)
            .map_err(|_| error("malformed_index", "managed index is invalid"))?;
        let anchor = Anchor {
            version: 1,
            volume_uuid: uuid.clone(),
            identity: index.project_identity.clone(),
        };
        validate(&anchor, &project.identity, &uuid)?;
        validate_index(&index, &anchor.identity)?;
        for task in index.tasks.iter().chain(&index.retired_tasks) {
            load_task(dir, &anchor.identity, &task.task_id)?;
        }
        if !req.confirm {
            return Ok(
                json!({"status":"reviewed","state_changed":false,"volume_uuid":uuid,"identity":anchor.identity}),
            );
        }
        let anchored = ProjectRoot {
            identity: anchor.identity,
            directory: project
                .directory
                .try_clone()
                .map_err(|_| error("io_error", "project directory cannot be held"))?,
        };
        create(&anchored, dir)?;
        Ok(json!({"status":"anchored","state_changed":true,"legacy_records_unchanged":true}))
    })
}
