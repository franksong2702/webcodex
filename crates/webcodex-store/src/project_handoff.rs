//! Bounded delivery outbox in the existing Server database. No command bodies,
//! credentials, output streams, retry authority, or independent task lifecycle.
use crate::Database;
use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HandoffBinding {
    pub session_id: String,
    pub project_id: String,
    pub client_id: String,
    pub project_path: String,
    pub task_id: String,
    pub root_fingerprint: String,
}

#[derive(Debug, Clone)]
pub struct HandoffPendingEvent {
    pub session_id: String,
    pub event_id: String,
    pub event: Value,
}

fn binding_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<HandoffBinding> {
    Ok(HandoffBinding {
        session_id: row.get(0)?,
        project_id: row.get(1)?,
        client_id: row.get(2)?,
        project_path: row.get(3)?,
        task_id: row.get(4)?,
        root_fingerprint: row.get(5)?,
    })
}

const SELECT_BINDING: &str = "SELECT session_id,project_id,client_id,project_path,task_id,root_fingerprint FROM wc_handoff_bindings WHERE session_id=?1";

const RETIREMENT_MATCH: &str = "r.project_id=b.project_id AND r.client_id=b.client_id AND r.project_path=b.project_path AND r.task_id=b.task_id AND r.root_fingerprint=b.root_fingerprint";

impl Database {
    /// Persistent freeze survives an ambiguous Runner response or Server restart.
    /// Binding identities remain intact so late receipts are never retargeted.
    pub fn handoff_retirement_started(&self, b: &HandoffBinding) -> anyhow::Result<bool> {
        Ok(self.conn.lock().unwrap().query_row(
            "SELECT EXISTS(SELECT 1 FROM wc_handoff_retirements WHERE project_id=?1 AND client_id=?2 AND project_path=?3 AND task_id=?4 AND root_fingerprint=?5)",
            params![b.project_id,b.client_id,b.project_path,b.task_id,b.root_fingerprint], |r| r.get(0))?)
    }

    /// Only after a definitive not-written Runner response. Unknown outcomes
    /// retain the fence until the exact task is reconciled.
    pub fn handoff_cancel_retirement(&self, b: &HandoffBinding) -> anyhow::Result<()> {
        self.conn.lock().unwrap().execute("DELETE FROM wc_handoff_retirements WHERE project_id=?1 AND client_id=?2 AND project_path=?3 AND task_id=?4 AND root_fingerprint=?5 AND retired=0",params![b.project_id,b.client_id,b.project_path,b.task_id,b.root_fingerprint])?;
        Ok(())
    }

    pub fn handoff_retire(&self, b: &HandoffBinding, finish: bool) -> anyhow::Result<()> {
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction()?;
        let unresolved: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM wc_handoff_bindings b WHERE b.project_id=?1 AND b.client_id=?2 AND b.project_path=?3 AND b.task_id=?4 AND b.root_fingerprint=?5 AND (EXISTS(SELECT 1 FROM wc_handoff_outbox o WHERE o.session_id=b.session_id) OR EXISTS(SELECT 1 FROM wc_handoff_capture_gaps g WHERE g.session_id=b.session_id)))",
            params![b.project_id,b.client_id,b.project_path,b.task_id,b.root_fingerprint], |r| r.get(0))?;
        anyhow::ensure!(!unresolved, "handoff_retirement_unresolved");
        if finish {
            let changed = tx.execute("UPDATE wc_handoff_retirements SET retired=1 WHERE project_id=?1 AND client_id=?2 AND project_path=?3 AND task_id=?4 AND root_fingerprint=?5", params![b.project_id,b.client_id,b.project_path,b.task_id,b.root_fingerprint])?;
            anyhow::ensure!(changed == 1, "handoff_retirement_not_started");
        } else {
            let count: usize =
                tx.query_row("SELECT COUNT(*) FROM wc_handoff_retirements", [], |r| {
                    r.get(0)
                })?;
            let exists: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM wc_handoff_retirements WHERE project_id=?1 AND client_id=?2 AND project_path=?3 AND task_id=?4 AND root_fingerprint=?5)",params![b.project_id,b.client_id,b.project_path,b.task_id,b.root_fingerprint],|r|r.get(0))?;
            anyhow::ensure!(
                exists || count < 4096,
                "handoff_retirement_capacity_exceeded"
            );
            tx.execute(
                "INSERT OR IGNORE INTO wc_handoff_retirements VALUES (?1,?2,?3,?4,?5,0)",
                params![
                    b.project_id,
                    b.client_id,
                    b.project_path,
                    b.task_id,
                    b.root_fingerprint
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }
}

impl Database {
    pub fn handoff_binding(&self, session_id: &str) -> anyhow::Result<Option<HandoffBinding>> {
        Ok(self
            .conn
            .lock()
            .unwrap()
            .query_row(SELECT_BINDING, [session_id], binding_row)
            .optional()?)
    }

    /// Binding is immutable for one Session. A new task uses a fresh explicit
    /// Session; queued evidence can therefore never be silently retargeted.
    pub fn handoff_bind(&self, binding: &HandoffBinding) -> anyhow::Result<()> {
        for field in [
            &binding.session_id,
            &binding.project_id,
            &binding.client_id,
            &binding.project_path,
            &binding.task_id,
            &binding.root_fingerprint,
        ] {
            anyhow::ensure!(
                !field.is_empty() && field.len() <= 4096 && !field.contains('\0'),
                "invalid_handoff_binding"
            );
        }
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction()?;
        let retired: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM wc_handoff_retirements WHERE project_id=?1 AND client_id=?2 AND project_path=?3 AND task_id=?4 AND root_fingerprint=?5)",params![binding.project_id,binding.client_id,binding.project_path,binding.task_id,binding.root_fingerprint],|r|r.get(0))?;
        anyhow::ensure!(!retired, "handoff_task_retired");
        if let Some(existing) = tx
            .query_row(SELECT_BINDING, [&binding.session_id], binding_row)
            .optional()?
        {
            anyhow::ensure!(existing == *binding, "handoff_binding_conflict");
            return Ok(());
        }
        let count: i64 =
            tx.query_row(&format!("SELECT COUNT(*) FROM wc_handoff_bindings b WHERE NOT EXISTS(SELECT 1 FROM wc_handoff_retirements r WHERE {RETIREMENT_MATCH} AND r.retired=1)"), [], |r| r.get(0))?;
        let total: usize =
            tx.query_row("SELECT COUNT(*) FROM wc_handoff_bindings", [], |r| r.get(0))?;
        anyhow::ensure!(total < 65536, "handoff_binding_history_capacity_exceeded");
        anyhow::ensure!(count < 1024, "handoff_binding_capacity_exceeded");
        tx.execute(
            "INSERT INTO wc_handoff_bindings VALUES (?1,?2,?3,?4,?5,?6)",
            params![
                binding.session_id,
                binding.project_id,
                binding.client_id,
                binding.project_path,
                binding.task_id,
                binding.root_fingerprint
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn handoff_enqueue(&self, session_id: &str, event: &Value, now: i64) -> anyhow::Result<()> {
        let object = event
            .as_object()
            .ok_or_else(|| anyhow::anyhow!("invalid_handoff_event"))?;
        let id = object
            .get("event_id")
            .and_then(Value::as_str)
            .ok_or_else(|| anyhow::anyhow!("missing_event_id"))?;
        anyhow::ensure!(
            !id.is_empty()
                && id.len() <= 128
                && id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b)),
            "invalid_event_id"
        );
        // Runtime facts only. Human free text belongs in the explicitly edited
        // checkpoint; never let a nested raw response enter this outbox.
        for (key, value) in object {
            anyhow::ensure!(
                matches!(
                    key.as_str(),
                    "event_id"
                        | "type"
                        | "source"
                        | "observed_at"
                        | "job_id"
                        | "tool"
                        | "status"
                        | "exit_code"
                        | "success"
                        | "unknown"
                        | "paths"
                ),
                "event_field_not_allowed"
            );
            anyhow::ensure!(!value.is_object(), "nested_event_not_allowed");
            if let Some(items) = value.as_array() {
                anyhow::ensure!(
                    key == "paths"
                        && items.len() <= 32
                        && items
                            .iter()
                            .all(|v| v.as_str().is_some_and(|s| s.len() <= 512)),
                    "invalid_event_paths"
                );
            }
        }
        let payload = serde_json::to_string(event)?;
        anyhow::ensure!(payload.len() <= 16 * 1024, "event_too_large");
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction()?;
        let old: Option<(String, String)> = tx
            .query_row(
                "SELECT session_id,event_json FROM wc_handoff_outbox WHERE event_id=?1",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        if let Some((old_session, old_payload)) = old {
            anyhow::ensure!(
                old_session == session_id && old_payload == payload,
                "event_id_conflict"
            );
            return Ok(());
        }
        let binding_exists: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM wc_handoff_bindings WHERE session_id=?1)",
            [session_id],
            |r| r.get(0),
        )?;
        anyhow::ensure!(binding_exists, "handoff_not_bound");
        let count: i64 =
            tx.query_row("SELECT COUNT(*) FROM wc_handoff_outbox", [], |r| r.get(0))?;
        anyhow::ensure!(count < 4096, "handoff_outbox_full");
        tx.execute(
            "INSERT INTO wc_handoff_outbox VALUES (?1,?2,?3,?4)",
            params![id, session_id, payload, now],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn handoff_pending(&self, session_id: &str) -> anyhow::Result<Vec<HandoffPendingEvent>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT event_id,event_json FROM wc_handoff_outbox WHERE session_id=?1 ORDER BY created_at,event_id LIMIT 32")?;
        let rows = stmt.query_map([session_id], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        let mut events = Vec::new();
        for row in rows {
            let (event_id, payload) = row?;
            events.push(HandoffPendingEvent {
                session_id: session_id.into(),
                event_id,
                event: serde_json::from_str(&payload)?,
            });
        }
        Ok(events)
    }

    pub fn handoff_pending_for_task(
        &self,
        binding: &HandoffBinding,
    ) -> anyhow::Result<Vec<HandoffPendingEvent>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT o.session_id,o.event_id,o.event_json FROM wc_handoff_outbox o JOIN wc_handoff_bindings b ON b.session_id=o.session_id WHERE b.project_id=?1 AND b.client_id=?2 AND b.project_path=?3 AND b.task_id=?4 AND b.root_fingerprint=?5 ORDER BY o.created_at,o.event_id LIMIT 32")?;
        let rows = stmt.query_map(
            params![
                binding.project_id,
                binding.client_id,
                binding.project_path,
                binding.task_id,
                binding.root_fingerprint
            ],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            },
        )?;
        let mut events = Vec::new();
        for row in rows {
            let (session_id, event_id, payload) = row?;
            events.push(HandoffPendingEvent {
                session_id,
                event_id,
                event: serde_json::from_str(&payload)?,
            });
        }
        Ok(events)
    }

    pub fn handoff_pending_count(
        &self,
        project_id: &str,
        project_path: &str,
    ) -> anyhow::Result<u64> {
        Ok(self.conn.lock().unwrap().query_row("SELECT COUNT(*) FROM wc_handoff_outbox o JOIN wc_handoff_bindings b ON b.session_id=o.session_id WHERE b.project_id=?1 AND b.project_path=?2", params![project_id,project_path], |r| r.get(0))?)
    }

    /// Only the same delivery target may acknowledge a durably saved event.
    pub fn handoff_ack(&self, session_id: &str, event_id: &str) -> anyhow::Result<()> {
        self.conn.lock().unwrap().execute(
            "DELETE FROM wc_handoff_outbox WHERE session_id=?1 AND event_id=?2",
            params![session_id, event_id],
        )?;
        Ok(())
    }
}

/// Capture terminal facts in the receipt transaction. A full outbox retains a
/// bounded, latched coverage gap; neither condition can masquerade as caught up.
pub(crate) fn capture_terminal(
    conn: &rusqlite::Connection,
    receipt: &webcodex_core::runner_job_receipt::RetainedJobReceipt,
) -> anyhow::Result<()> {
    use sha2::{Digest, Sha256};
    let context = &receipt.snapshot.context;
    let Some(session) = context.workflow_session_id.as_deref() else {
        return Ok(());
    };
    let Some(binding) = conn
        .query_row(SELECT_BINDING, [session], binding_row)
        .optional()?
    else {
        return Ok(());
    };
    if binding.client_id != receipt.client_id
        || Some(binding.project_id.as_str()) != context.runtime_project_id.as_deref()
        // "." is the wire marker for the registered project root. Exact
        // Session/client/project identity anchors this queued fact; delivery
        // still rechecks the bound absolute path and root fingerprint.
        || !matches!(context.project_cwd.as_deref(), Some("."))
            && Some(binding.project_path.as_str()) != context.project_cwd.as_deref()
    {
        return Ok(());
    }
    let count: i64 = conn.query_row("SELECT COUNT(*) FROM wc_handoff_outbox", [], |r| r.get(0))?;
    if count >= 4096 {
        conn.execute(
            "INSERT OR IGNORE INTO wc_handoff_capture_gaps VALUES (?1,'outbox_capacity')",
            [session],
        )?;
        return Ok(());
    }
    let id = format!(
        "job-terminal-{:x}",
        Sha256::digest(receipt.snapshot.job_id.as_bytes())
    );
    let mut event = serde_json::json!({"event_id":id,"type":"job_terminal","source":"webcodex",
        "job_id":receipt.snapshot.job_id,"job_update_seq":receipt.snapshot.update_seq,"status":receipt.snapshot.status,"observed_at":receipt.terminal_observed_at});
    if let Some(code) = receipt.snapshot.exit_code {
        event["exit_code"] = code.into();
    }
    conn.execute(
        "INSERT OR IGNORE INTO wc_handoff_outbox VALUES (?1,?2,?3,?4)",
        params![
            id,
            session,
            serde_json::to_string(&event)?,
            receipt.terminal_observed_at
        ],
    )?;
    Ok(())
}

impl Database {
    pub fn handoff_capture_gap(&self, session: &str) -> anyhow::Result<()> {
        self.conn.lock().unwrap().execute("INSERT OR IGNORE INTO wc_handoff_capture_gaps SELECT session_id,'capture_failed' FROM wc_handoff_bindings WHERE session_id=?1", [session])?;
        Ok(())
    }

    /// Current known delivery state, scoped to the exact file identity read by
    /// the authorized caller. Zero pending is never a full coverage guarantee.
    pub fn handoff_source_status(
        &self,
        project: &str,
        path: &str,
        task: Option<&str>,
        fingerprint: Option<&str>,
    ) -> anyhow::Result<Value> {
        let conn = self.conn.lock().unwrap();
        let counts: (u64,u64,u64) = conn.query_row("SELECT COUNT(*), COALESCE(SUM((SELECT COUNT(*) FROM wc_handoff_outbox o WHERE o.session_id=b.session_id)),0), COALESCE(SUM(EXISTS(SELECT 1 FROM wc_handoff_capture_gaps g WHERE g.session_id=b.session_id)),0) FROM wc_handoff_bindings b WHERE b.project_id=?1 AND b.project_path=?2 AND (?3 IS NULL OR b.task_id=?3) AND (?4 IS NULL OR b.root_fingerprint=?4)", params![project,path,task,fingerprint], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?)))?;
        let retiring: u64 = conn.query_row("SELECT COUNT(*) FROM wc_handoff_retirements WHERE project_id=?1 AND project_path=?2 AND (?3 IS NULL OR task_id=?3) AND (?4 IS NULL OR root_fingerprint=?4) AND retired=0",params![project,path,task,fingerprint],|r|r.get(0))?;
        Ok(
            serde_json::json!({"bindings":counts.0,"pending":counts.1,"capture_gaps":counts.2,"retiring":retiring,
            "status":if counts.2>0 {"incomplete"} else if counts.1>0 {"pending"} else if retiring>0 {"retiring"} else if counts.0==0 {"unbound"} else {"caught_up"},
            "coverage":"known_recorded_events_only"}),
        )
    }
}
