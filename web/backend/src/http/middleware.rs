use std::time::{Duration, Instant};

use axum::{
    extract::State,
    http::{HeaderMap, Method, Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;

use crate::state::{AppState, RateLimitBucket};

pub fn bearer_token(headers: &HeaderMap) -> Option<String> {
    headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "))
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

pub fn cookie_value(headers: &HeaderMap, name: &str) -> Option<String> {
    headers
        .get(axum::http::header::COOKIE)
        .and_then(|value| value.to_str().ok())
        .and_then(|raw| {
            raw.split(';').map(str::trim).find_map(|pair| {
                pair.split_once('=')
                    .filter(|(key, _)| key.trim() == name)
                    .map(|(_, value)| value.trim().to_string())
            })
        })
        .filter(|value| !value.is_empty())
}

pub fn origin(headers: &HeaderMap) -> Option<String> {
    headers
        .get(axum::http::header::ORIGIN)
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn client_ip(headers: &HeaderMap) -> String {
    headers
        .get("x-forwarded-for")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split(',').next())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .or_else(|| {
            headers
                .get("x-real-ip")
                .and_then(|value| value.to_str().ok())
                .map(str::trim)
                .filter(|value| !value.is_empty())
        })
        .unwrap_or("unknown")
        .to_string()
}

fn rate_limit_key(category: &str, headers: &HeaderMap) -> String {
    let ip = client_ip(headers);
    let origin = origin(headers).unwrap_or_else(|| "no-origin".to_string());
    format!("{category}|{ip}|{origin}")
}

/// Background polling of device-link answers: authenticated or keyed by a random request id,
/// never a credential attempt. Several screens and tabs poll every 3.5–5 s, so these reads
/// get their own bucket instead of exhausting the 20/min `auth` bucket and locking out sign-in.
const POLL_RATE_LIMIT_MAX_ATTEMPTS: u32 = 240;

fn is_device_link_poll(method: &Method, path: &str) -> bool {
    if method != Method::GET {
        return false;
    }
    let Some(rest) = path.strip_prefix("/api/v1/auth/device-link/lan/") else {
        return false;
    };
    rest == "inbox"
        || rest == "pending-request"
        || ["result/", "poll/", "mobile-poll/"].iter().any(|prefix| {
            rest.strip_prefix(prefix)
                .is_some_and(|id| !id.is_empty() && !id.contains('/'))
        })
}

fn classify_request(method: &Method, path: &str) -> Option<&'static str> {
    if is_device_link_poll(method, path) {
        return Some("poll");
    }

    if path.starts_with("/api/v1/auth/native/")
        || path.starts_with("/api/v1/auth/sign-in")
        || path.starts_with("/api/v1/auth/sign-up")
        || path.starts_with("/api/v1/auth/refresh")
        || path.starts_with("/api/v1/auth/sign-out")
        || path.starts_with("/api/v1/auth/sign-out-all")
        || path.starts_with("/api/v1/auth/node-link/")
        || path.starts_with("/api/v1/auth/device-link/")
        || path.starts_with("/api/v1/auth/dev-bootstrap")
    {
        return Some("auth");
    }

    if path.starts_with("/api/v1/sync") || path.starts_with("/api/v1/integrations/") {
        return Some("sensitive");
    }

    None
}

pub async fn rate_limit_middleware(
    State(state): State<AppState>,
    request: Request<axum::body::Body>,
    next: Next,
) -> Response {
    let path = request.uri().path().to_string();
    let headers = request.headers().clone();

    if let Some(category) = classify_request(request.method(), &path) {
        let (window_secs, max_attempts) = match category {
            "auth" => (
                state.settings.auth.auth_rate_limit_window_secs,
                state.settings.auth.auth_rate_limit_max_attempts,
            ),
            "poll" => (
                state.settings.auth.sensitive_rate_limit_window_secs,
                POLL_RATE_LIMIT_MAX_ATTEMPTS,
            ),
            _ => (
                state.settings.auth.sensitive_rate_limit_window_secs,
                state.settings.auth.sensitive_rate_limit_max_attempts,
            ),
        };

        let now = Instant::now();
        let mut store = state
            .rate_limits
            .buckets
            .lock()
            .expect("rate limit store mutex poisoned");

        store.retain(|_, bucket| {
            now.duration_since(bucket.window_started_at) < Duration::from_secs(window_secs * 2)
        });

        let key = rate_limit_key(category, &headers);
        let bucket = store.entry(key).or_insert_with(|| RateLimitBucket {
            window_started_at: now,
            count: 0,
        });

        if now.duration_since(bucket.window_started_at) >= Duration::from_secs(window_secs) {
            bucket.window_started_at = now;
            bucket.count = 0;
        }

        bucket.count += 1;
        if bucket.count > max_attempts {
            return (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests. Please slow down and try again shortly.",
                        "details": {
                            "category": category,
                            "windowSeconds": window_secs,
                            "maxAttempts": max_attempts,
                        }
                    }
                })),
            )
                .into_response();
        }
    }

    next.run(request).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn device_link_polling_does_not_spend_the_auth_bucket() {
        for path in [
            "/api/v1/auth/device-link/lan/inbox",
            "/api/v1/auth/device-link/lan/pending-request",
            "/api/v1/auth/device-link/lan/result/abc",
            "/api/v1/auth/device-link/lan/poll/abc",
            "/api/v1/auth/device-link/lan/mobile-poll/abc",
        ] {
            assert_eq!(classify_request(&Method::GET, path), Some("poll"), "{path}");
        }
    }

    #[test]
    fn credential_and_link_actions_stay_in_the_auth_bucket() {
        for (method, path) in [
            (Method::POST, "/api/v1/auth/native/sign-in"),
            (Method::POST, "/api/v1/auth/sign-in"),
            (Method::POST, "/api/v1/auth/refresh"),
            (Method::POST, "/api/v1/auth/device-link/lan/inbox"),
            (Method::POST, "/api/v1/auth/device-link/lan/connect"),
            (Method::POST, "/api/v1/auth/device-link/lan/approve"),
            (Method::GET, "/api/v1/auth/device-link/lan/poll/"),
            (Method::GET, "/api/v1/auth/device-link/lan/poll/a/b"),
        ] {
            assert_eq!(
                classify_request(&method, path),
                Some("auth"),
                "{method} {path}"
            );
        }
        assert_eq!(
            classify_request(&Method::GET, "/api/v1/sync/x"),
            Some("sensitive")
        );
        assert_eq!(classify_request(&Method::GET, "/api/v1/workspaces"), None);
    }
}
