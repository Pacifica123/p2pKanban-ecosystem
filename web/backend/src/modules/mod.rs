use axum::Router;

use crate::state::AppState;

pub mod activity;
pub mod appearance;
pub mod audit;
pub mod boards;
pub mod cards;
pub mod checklists;
pub mod comments;
pub mod common;
pub mod integrations;
pub mod labels;
pub mod sync;
pub mod users;
pub mod workspaces;

pub fn router() -> Router<AppState> {
    Router::new()
        .merge(activity::router())
        .merge(appearance::router())
        .merge(audit::router())
        .merge(boards::router())
        .merge(cards::router())
        .merge(checklists::router())
        .merge(comments::router())
        .merge(integrations::router())
        .merge(labels::router())
        .merge(sync::router())
        .merge(users::router())
        .merge(workspaces::router())
}
