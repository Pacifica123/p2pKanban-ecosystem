use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::Instant,
};

use sqlx::PgPool;

use crate::config::Settings;

#[derive(Debug)]
pub struct RateLimitBucket {
    pub window_started_at: Instant,
    pub count: u32,
}

#[derive(Debug, Default)]
pub struct RateLimitStore {
    pub buckets: Mutex<HashMap<String, RateLimitBucket>>,
}

#[derive(Clone)]
pub struct AppState {
    pub settings: Arc<Settings>,
    pub db: PgPool,
    pub rate_limits: Arc<RateLimitStore>,
}

impl AppState {
    pub fn new(settings: Settings, db: PgPool) -> Self {
        Self {
            settings: Arc::new(settings),
            db,
            rate_limits: Arc::new(RateLimitStore::default()),
        }
    }
}
