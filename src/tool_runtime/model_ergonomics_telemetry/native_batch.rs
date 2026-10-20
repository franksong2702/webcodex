//! Payload-free cardinality of the current admitted canonical invocation.
//!
//! Requested entries are independent of returned, successful, or completed
//! entries. No nested invocation counts are inferred from an outer call.

use crate::tool_runtime::ToolCall;
use serde::Serialize;

// Both canonical ToolCall deserializers enforce one through eight entries.
const MAX_ENTRIES: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub(crate) enum NativeBatchFacts {
    ReadFiles { requested_items: u64 },
    SearchProjectTexts { requested_queries: u64 },
}

pub(super) fn from_admitted_call(call: &ToolCall) -> Option<NativeBatchFacts> {
    match call {
        ToolCall::ReadFiles { items, .. } if (1..=MAX_ENTRIES).contains(&items.len()) => {
            Some(NativeBatchFacts::ReadFiles {
                requested_items: items.len() as u64,
            })
        }
        ToolCall::SearchProjectTexts { queries, .. }
            if (1..=MAX_ENTRIES).contains(&queries.len()) =>
        {
            Some(NativeBatchFacts::SearchProjectTexts {
                requested_queries: queries.len() as u64,
            })
        }
        _ => None,
    }
}

#[cfg(test)]
#[path = "native_batch_tests.rs"]
mod tests;
