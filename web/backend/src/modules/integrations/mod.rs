pub mod projects;
pub mod dto;
pub mod handler;
pub mod provider;
pub mod service;

use axum::{
    routing::{get, post},
    Router,
};

use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new().route("/integrations/projects",get(projects::list).post(projects::create))
      .route("/integrations/projects/{projectId}/receipts",get(projects::receipts).post(projects::ingest))
      .route("/integrations/projects/{projectId}/receipts/preview",post(projects::preview))
        .route("/integrations/providers", get(handler::list_providers))
        .route(
            "/integrations/providers/{providerKey}",
            get(handler::get_provider_detail),
        )
        .route(
            "/integrations/import-jobs",
            post(handler::create_import_job),
        )
        .route(
            "/integrations/export-jobs",
            post(handler::create_export_job),
        )
        .route(
            "/integrations/import-export/capabilities",
            get(handler::get_import_export_capabilities),
        )
        .route(
            "/integrations/import-export/exports",
            post(handler::create_portable_export),
        )
        .route(
            "/integrations/import-export/imports/preview",
            post(handler::preview_import_bundle),
        )
        .route(
            "/integrations/import-export/imports",
            post(handler::create_import_execution),
        )
        .route(
            "/integrations/webhooks/{providerKey}",
            post(handler::receive_webhook),
        )
}
