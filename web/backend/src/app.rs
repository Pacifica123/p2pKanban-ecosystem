use std::time::Duration;

use axum::{
    error_handling::HandleErrorLayer,
    http::{header, HeaderName, HeaderValue, Method, StatusCode},
    middleware,
    routing::get,
    BoxError, Router,
};
use tower::timeout::TimeoutLayer;
use tower::ServiceBuilder;
use tower_http::{
    cors::{AllowOrigin, CorsLayer},
    limit::RequestBodyLimitLayer,
    trace::{DefaultMakeSpan, DefaultOnRequest, DefaultOnResponse, TraceLayer},
};

use crate::{
    http::{
        middleware::rate_limit_middleware,
        router::{api_router, root_health},
    },
    state::AppState,
};

pub fn build_app(state: AppState) -> Router {
    let body_limit_bytes = state.settings.http.body_limit_mb * 1024 * 1024;

    let allowed_origins = state
        .settings
        .http
        .cors_allowed_origins
        .iter()
        .filter_map(|value| HeaderValue::from_str(value).ok())
        .collect::<Vec<_>>();

    let mut allowed_headers = vec![header::AUTHORIZATION, header::CONTENT_TYPE, header::ACCEPT];
    if state.settings.dev_header_auth_allowed() {
        allowed_headers.push(HeaderName::from_static("x-user-id"));
    }

    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(allowed_origins))
        .allow_credentials(true)
        .allow_methods([
            Method::GET,
            Method::POST,
            Method::PATCH,
            Method::PUT,
            Method::DELETE,
            Method::OPTIONS,
        ])
        .allow_headers(allowed_headers);

    let middleware_stack = ServiceBuilder::new()
        .layer(RequestBodyLimitLayer::new(body_limit_bytes))
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(DefaultMakeSpan::new().include_headers(false))
                .on_request(DefaultOnRequest::new().level(tracing::Level::INFO))
                .on_response(DefaultOnResponse::new().level(tracing::Level::INFO)),
        )
        .layer(cors)
        .layer(HandleErrorLayer::new(|_: BoxError| async {
            StatusCode::REQUEST_TIMEOUT
        }))
        .layer(TimeoutLayer::new(Duration::from_secs(30)));

    Router::new()
        .route("/health", get(root_health))
        .nest("/api/v1", api_router())
        .layer(middleware::from_fn_with_state(
            state.clone(),
            rate_limit_middleware,
        ))
        .layer(middleware_stack)
        .with_state(state)
}
