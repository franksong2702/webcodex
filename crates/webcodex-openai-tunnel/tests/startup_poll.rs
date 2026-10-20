mod support;
use support::*;
use webcodex_openai_tunnel::policy::{DeadlinePolicy, Limits};

#[tokio::test]
async fn initial_poll_uses_short_wait_then_returns_to_normal_long_poll() {
    let mut cp = Server::new().await;
    let mcp = Server::new().await;
    let client = client(&cp, &mcp, Limits::default(), DeadlinePolicy::default());
    let health = client.health();
    let (stop, task) = start(client);

    let first = cp.next().await;
    assert_eq!(first.method, "GET");
    assert!(
        first.path.ends_with("/poll?limit=8&timeout_ms=1000"),
        "{}",
        first.path
    );
    assert!(
        !health.is_ready(),
        "a request in flight is not proof of a successful poll"
    );
    // Simulate a service-held successful empty poll without any real network.
    tokio::time::sleep(std::time::Duration::from_millis(65)).await;
    first.respond(204, "");

    let second = cp.next().await;
    assert!(
        health.is_ready(),
        "a successful empty poll establishes readiness"
    );
    let (attempts, request_ms) = health.initial_poll_details().unwrap();
    assert_eq!(attempts, 1);
    assert!(
        request_ms >= 50,
        "HTTP wait was not measured: {request_ms}ms"
    );
    assert!(request_ms <= health.initial_poll_ms().unwrap());
    assert!(
        second.path.ends_with("/poll?limit=8&timeout_ms=15000"),
        "{}",
        second.path
    );
    second.respond(204, "");
    assert_eq!(finish(stop, task).await, Ok(()));
}

#[tokio::test]
async fn transient_initial_failure_keeps_short_poll_until_success() {
    let mut cp = Server::new().await;
    let mcp = Server::new().await;
    let client = client(&cp, &mcp, Limits::default(), DeadlinePolicy::default());
    let health = client.health();
    let (stop, task) = start(client);

    let first = cp.next().await;
    assert!(first.path.contains("timeout_ms=1000"));
    first.respond(503, "");
    let retry = cp.next().await;
    assert!(retry.path.contains("timeout_ms=1000"));
    assert!(!health.is_ready());
    retry.respond(204, "");
    let steady = cp.next().await;
    let (attempts, request_ms) = health.initial_poll_details().unwrap();
    assert_eq!(attempts, 2);
    assert!(request_ms <= health.initial_poll_ms().unwrap());
    assert!(steady.path.contains("timeout_ms=15000"));
    steady.respond(204, "");
    assert_eq!(finish(stop, task).await, Ok(()));
}
