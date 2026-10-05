use std::time::{Duration, Instant};

use axum::{
    extract::State,
    http::{HeaderMap, Request, StatusCode},
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

fn classify_request(path: &str) -> Option<(&'static str, u64, u32)> {
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
        return Some(("auth", 0, 0));
    }

    if path.starts_with("/api/v1/sync") || path.starts_with("/api/v1/integrations/") {
        return Some(("sensitive", 0, 0));
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

    if let Some((category, _, _)) = classify_request(&path) {
        let (window_secs, max_attempts) = match category {
            "auth" => (
                state.settings.auth.auth_rate_limit_window_secs,
                state.settings.auth.auth_rate_limit_max_attempts,
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
