//! Node side of `p2p-kanban-error-report/1` (contracts/error-report/1):
//!
//! - every response carries `x-p2p-kanban-node: <version>; build=<…>; commit=<…>`;
//! - every 5xx the node produces carries `errorId` (UUID v7) in the body and in
//!   `x-p2p-error-id`; each request runs in a span with that `error_id`, so the
//!   cause logged by the handler and the id the client copies are on one line;
//! - a panicking handler becomes the same 500 with `errorId` instead of a
//!   dropped connection (which the gateway reports as a bodiless 502).

use std::sync::OnceLock;

use axum::{
    body::{to_bytes, Body},
    extract::Request,
    http::{header, HeaderValue, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::{json, Value};
use tracing::Instrument;
use uuid::Uuid;

pub const NODE_HEADER: &str = "x-p2p-kanban-node";
pub const ERROR_ID_HEADER: &str = "x-p2p-error-id";
const BODY_LIMIT: usize = 256 * 1024;

fn identity(value: Option<String>, valid: impl Fn(&str) -> bool) -> Option<String> {
    value.map(|v| v.trim().to_string()).filter(|v| !v.is_empty() && v != "unknown" && valid(v))
}

/// Image fingerprint: the hex suffix of `P2PKANBAN_BUILD` (`2.1.0-8087da08253b`), else the tag itself.
pub fn build_id() -> Option<String> {
    static BUILD: OnceLock<Option<String>> = OnceLock::new();
    BUILD.get_or_init(|| {
        identity(std::env::var("P2PKANBAN_BUILD").ok(), |v| v.len() <= 64 && v.chars().all(|c| c.is_ascii_alphanumeric() || "._-".contains(c)))
            .map(|tag| match tag.rsplit_once('-') {
                Some((_, suffix)) if suffix.len() >= 7 && suffix.chars().all(|c| c.is_ascii_hexdigit()) => suffix.to_string(),
                _ => tag,
            })
    }).clone()
}

/// Monorepo commit the node was built from (`P2PKANBAN_SOURCE_REVISION`, 40 hex).
pub fn source_commit() -> Option<String> {
    static COMMIT: OnceLock<Option<String>> = OnceLock::new();
    COMMIT.get_or_init(|| identity(std::env::var("P2PKANBAN_SOURCE_REVISION").ok(),
        |v| v.len() == 40 && v.chars().all(|c| c.is_ascii_hexdigit()))).clone()
}

pub fn node_header() -> HeaderValue {
    static VALUE: OnceLock<HeaderValue> = OnceLock::new();
    VALUE.get_or_init(|| {
        let text = format!("{}; build={}; commit={}", env!("CARGO_PKG_VERSION"),
            build_id().unwrap_or_else(|| "unknown".into()), source_commit().unwrap_or_else(|| "unknown".into()));
        HeaderValue::from_str(&text).unwrap_or_else(|_| HeaderValue::from_static("unknown"))
    }).clone()
}

fn panic_text(payload: &(dyn std::any::Any + Send)) -> String {
    payload.downcast_ref::<&str>().map(|s| s.to_string())
        .or_else(|| payload.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "panic without message".into())
}

/// Put `errorId` into an error envelope; a body that is not one becomes one.
pub fn with_error_id(body: &[u8], status: StatusCode, error_id: &str) -> Value {
    let mut value: Value = serde_json::from_slice(body).unwrap_or(Value::Null);
    match value.get_mut("error").and_then(Value::as_object_mut) {
        Some(error) => {
            error.insert("errorId".into(), json!(error_id));
            value
        }
        None => json!({"error": {
            "code": "internal_error",
            "message": status.canonical_reason().unwrap_or("Internal server error"),
            "details": if body.is_empty() { Value::Null } else { json!(String::from_utf8_lossy(body)) },
            "errorId": error_id,
        }}),
    }
}

pub async fn error_report_middleware(request: Request, next: Next) -> Response {
    let error_id = Uuid::now_v7().to_string();
    let method = request.method().clone();
    let path = request.uri().path().to_string();
    let span = tracing::info_span!("request", error_id = %error_id);
    let outcome = tokio::spawn(next.run(request).instrument(span.clone())).await;
    let mut response = match outcome {
        Ok(response) => response,
        Err(join) => {
            let reason = if join.is_panic() { panic_text(&*join.into_panic()) } else { "handler task cancelled".into() };
            tracing::error!(error_id = %error_id, %method, %path, panic = %reason, "handler panicked; answered 500");
            (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": {
                "code": "internal_error", "message": "Internal server error", "details": null, "errorId": error_id,
            }}))).into_response()
        }
    };
    let status = response.status();
    if status.is_server_error() && !response.headers().contains_key(ERROR_ID_HEADER) {
        let (mut parts, body) = response.into_parts();
        let bytes = to_bytes(body, BODY_LIMIT).await.unwrap_or_default();
        let value = with_error_id(&bytes, status, &error_id);
        let encoded = serde_json::to_vec(&value).unwrap_or_default();
        parts.headers.insert(header::CONTENT_TYPE, HeaderValue::from_static("application/json"));
        parts.headers.insert(header::CONTENT_LENGTH, HeaderValue::from(encoded.len()));
        response = Response::from_parts(parts, Body::from(encoded));
        tracing::error!(error_id = %error_id, %method, %path, status = status.as_u16(), "answered with a server error");
    }
    if status.is_server_error() {
        if let Ok(value) = HeaderValue::from_str(&error_id) {
            response.headers_mut().entry(ERROR_ID_HEADER).or_insert(value);
        }
    }
    response.headers_mut().insert(NODE_HEADER, node_header());
    response
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn error_id_joins_the_existing_envelope_or_wraps_plain_text() {
        let id = "01a11200-0000-7000-8000-00000000e500";
        let envelope = br#"{"error":{"code":"internal_error","message":"Internal server error","details":null}}"#;
        assert_eq!(with_error_id(envelope, StatusCode::INTERNAL_SERVER_ERROR, id)["error"]["errorId"], id);
        let wrapped = with_error_id(b"upstream died", StatusCode::BAD_GATEWAY, id);
        assert_eq!(wrapped["error"]["details"], "upstream died");
        assert_eq!(wrapped["error"]["code"], "internal_error");
    }
}
