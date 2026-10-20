pub fn greeting() -> &'static str {
    "hello"
}

pub fn topic() -> &'static str {
    "keep"
}

#[cfg(test)]
mod tests {
    #[test]
    fn greeting_matches_target() {
        assert_eq!(super::greeting(), "hello recovered");
        assert_eq!(super::topic(), "keep");
    }
}
