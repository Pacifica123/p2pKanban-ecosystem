use std::time::Duration;

use sqlx::{postgres::PgPoolOptions, PgPool};

use crate::config::DatabaseSettings;

pub async fn create_pool(cfg: &DatabaseSettings) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(cfg.max_connections)
        .min_connections(cfg.min_connections)
        .acquire_timeout(Duration::from_secs(cfg.connect_timeout_secs))
        .connect(&cfg.url)
        .await
}
