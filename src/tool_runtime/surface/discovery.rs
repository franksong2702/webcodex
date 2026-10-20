//! Deterministic lexical retrieval over already-admitted canonical descriptors.
//! This is selection metadata only: no aliases, schema expansion, or authority.
use webcodex_tool_contracts::registry::ToolDescriptor;

/// Query work is bounded by the manifest's 200-character input limit and the
/// static catalog. Score once per descriptor, then break ties by canonical name.
pub(crate) fn rank<'a>(specs: &mut Vec<&'a ToolDescriptor>, query: &str) {
    // Underscore-separated keywords support partial names, but each supplied
    // term must have evidence. Unknown task words cannot be discarded merely
    // because a generic word such as "repository" occurs in safety prose.
    let token_query = query.contains('_')
        && query
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '_');
    let terms = terms(query);
    let mut ranked = specs
        .iter()
        .filter_map(|spec| {
            let exact = spec.name == query;
            let name = terms_for_name(&spec.name);
            let name_hits = terms.iter().filter(|term| name.contains(term)).count();
            let keyword_terms = spec
                .discovery_keywords
                .iter()
                .flat_map(|keyword| terms_for_name(keyword))
                .collect::<std::collections::BTreeSet<_>>();
            let english_hits = terms
                .iter()
                .filter(|term| keyword_terms.contains(*term))
                .count();
            // Match declared multi-character Chinese vocabulary, never arbitrary
            // individual CJK characters or corpus-specific sentence aliases.
            let chinese_hits = spec
                .discovery_keywords
                .iter()
                .filter(|keyword| !keyword.is_ascii() && query.contains(**keyword))
                .count();
            let keyword_hits = english_hits + chinese_hits;
            let description_text = spec.description.to_lowercase();
            let description = terms_for_name(&description_text);
            let description_hits = terms
                .iter()
                .filter(|term| description.contains(term))
                .count();
            if token_query
                && !terms.iter().all(|term| {
                    name.contains(term)
                        || keyword_terms.contains(term)
                        || description.contains(term)
                })
            {
                return None;
            }
            let score = name_hits * 12 + keyword_hits * 6 + description_hits;
            (exact || score > 0).then_some((*spec, (exact, score, name_hits, keyword_hits)))
        })
        .collect::<Vec<_>>();
    ranked.sort_by(|(left, left_score), (right, right_score)| {
        right_score
            .cmp(left_score)
            .then_with(|| left.name.cmp(&right.name))
    });
    *specs = ranked.into_iter().map(|(spec, _)| spec).collect();
}

fn terms_for_name(text: &str) -> Vec<&str> {
    text.split(|ch: char| !ch.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .map(singular)
        .collect()
}

fn singular(word: &str) -> &str {
    if word.len() > 3 && word.ends_with('s') && !word.ends_with("ss") && !word.ends_with("us") {
        &word[..word.len() - 1]
    } else {
        word
    }
}

fn terms(text: &str) -> Vec<&str> {
    let mut terms = terms_for_name(text);
    terms.retain(|word| {
        word.len() > 1
            && !matches!(
                *word,
                "the"
                    | "and"
                    | "or"
                    | "of"
                    | "to"
                    | "in"
                    | "on"
                    | "at"
                    | "for"
                    | "from"
                    | "with"
                    | "without"
                    | "by"
                    | "as"
                    | "an"
                    | "is"
                    | "are"
                    | "be"
                    | "was"
                    | "were"
                    | "this"
                    | "that"
                    | "these"
                    | "those"
                    | "it"
                    | "my"
                    | "me"
                    | "we"
                    | "please"
                    | "can"
                    | "could"
                    | "would"
                    | "want"
                    | "need"
                    | "whether"
                    | "how"
                    | "what"
                    | "which"
                    | "some"
                    | "several"
                    | "few"
                    | "one"
                    | "all"
                    | "do"
                    | "doe"
            )
    });
    terms.sort_unstable();
    terms.dedup();
    terms
}
