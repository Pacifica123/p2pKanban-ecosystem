use axum::{extract::State, routing::get, Router};

use crate::{
    auth,
    http::{
        health::health_payload,
        response::{ok, ApiEnvelope, HealthPayload},
    },
    modules,
    state::AppState,
};

pub fn api_router() -> Router<AppState> {
    Router::new()
        .route("/health", get(api_health))
        .merge(auth::router())
        .merge(modules::router())
}

pub async fn root_health(State(state): State<AppState>) -> axum::Json<ApiEnvelope<HealthPayload>> {
    ok(health_payload(&state))
}

async fn api_health(State(state): State<AppState>) -> axum::Json<ApiEnvelope<HealthPayload>> {
    ok(health_payload(&state))
}
