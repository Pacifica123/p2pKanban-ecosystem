use crate::{http::response::HealthPayload, state::AppState};

pub fn health_payload(state: &AppState) -> HealthPayload {
    HealthPayload {
        status: "ok",
        service: state.settings.app.name.clone(),
        version: env!("CARGO_PKG_VERSION"),
        env: state.settings.app.env.clone(),
    }
}
