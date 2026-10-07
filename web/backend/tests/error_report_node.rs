//! Node side of contracts/error-report/1: errorId on every 5xx (body, header),
//! panics answered as 500 with errorId, version header on every response.
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
    middleware,
    routing::get,
    Router,
};
use p2p_planner_backend::{error::AppError, http::error_report::{error_report_middleware, ERROR_ID_HEADER, NODE_HEADER}};
use serde_json::Value;
use tower::ServiceExt;

fn app() -> Router {
    Router::new()
        .route("/ok", get(|| async { "ok" }))
        .route("/internal", get(|| async { Err::<(), _>(AppError::internal()) }))
        .route("/conflict", get(|| async { Err::<(), _>(AppError::conflict("Нет досок владельца для подключения")) }))
        .route("/plain-503", get(|| async { (StatusCode::SERVICE_UNAVAILABLE, "relay pool exhausted") }))
        .route("/panic", get(|| async {
            let text = "Импорт: создание комментария";
            // The 2026-10-06 bug: slicing UTF-8 inside a letter.
            let _ = &text[..1];
            "unreachable"
        }))
        .layer(middleware::from_fn(error_report_middleware))
}

async fn call(path: &str) -> (StatusCode, axum::http::HeaderMap, Value) {
    let response = app().oneshot(Request::get(path).body(Body::empty()).unwrap()).await.unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (status, headers, serde_json::from_slice(&bytes).unwrap_or(Value::Null))
}

fn is_uuid_v7(value: &str) -> bool {
    let parts: Vec<&str> = value.split('-').collect();
    parts.iter().map(|p| p.len()).collect::<Vec<_>>() == [8, 4, 4, 4, 12]
        && value.chars().all(|c| c == '-' || c.is_ascii_digit() || ('a'..='f').contains(&c))
        && parts[2].starts_with('7')
        && "89ab".contains(&parts[3][..1])
}

fn node_header_ok(headers: &axum::http::HeaderMap) {
    let value = headers.get(NODE_HEADER).expect("x-p2p-kanban-node on every response").to_str().unwrap();
    let parts: Vec<&str> = value.split("; ").collect();
    assert_eq!(parts.len(), 3, "{value}");
    assert_eq!(parts[0], env!("CARGO_PKG_VERSION"));
    assert!(parts[1].starts_with("build=") && parts[2].starts_with("commit="), "{value}");
}

#[tokio::test]
async fn server_errors_carry_the_same_error_id_in_body_and_header() {
    for path in ["/internal", "/plain-503", "/panic"] {
        let (status, headers, body) = call(path).await;
        assert!(status.is_server_error(), "{path}: {status}");
        let id = body["error"]["errorId"].as_str().unwrap_or_else(|| panic!("{path}: {body}"));
        assert!(is_uuid_v7(id), "{path}: {id}");
        assert_eq!(headers.get(ERROR_ID_HEADER).unwrap().to_str().unwrap(), id, "{path}");
        assert!(body["error"]["code"].as_str().unwrap().chars().all(|c| c.is_ascii_lowercase() || c == '_'));
        node_header_ok(&headers);
    }
    let (status, _, body) = call("/panic").await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR, "a panic is a 500 with a body, not a dropped connection");
    assert_eq!(body["error"]["code"], "internal_error");
    let (_, _, plain) = call("/plain-503").await;
    assert_eq!(plain["error"]["details"], "relay pool exhausted");
}

#[tokio::test]
async fn client_errors_and_success_have_no_error_id_but_carry_the_node_version() {
    let (status, headers, body) = call("/conflict").await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert!(body["error"].get("errorId").is_none() && headers.get(ERROR_ID_HEADER).is_none());
    node_header_ok(&headers);
    let (status, headers, _) = call("/ok").await;
    assert_eq!(status, StatusCode::OK);
    node_header_ok(&headers);
}
