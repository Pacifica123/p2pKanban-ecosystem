use crate::{
    http::{error_report, response::HealthPayload},
    state::AppState,
};

pub fn health_payload(state: &AppState) -> HealthPayload {
    HealthPayload {
        status: "ok",
        service: state.settings.app.name.clone(),
        version: env!("CARGO_PKG_VERSION"),
        env: state.settings.app.env.clone(),
        build: error_report::build_id(),
        commit: error_report::source_commit(),
    }
}
