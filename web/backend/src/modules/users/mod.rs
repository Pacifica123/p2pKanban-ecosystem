pub mod dto;
pub mod handler;
pub mod repo;
pub mod service;

use axum::{
    routing::{delete, get},
    Router,
};

use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/me", get(handler::get_current_user))
        .route("/me/devices", get(handler::list_devices))
        .route("/me/devices/{deviceId}", delete(handler::revoke_device))
}
