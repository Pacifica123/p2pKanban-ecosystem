pub(crate) mod repo;
#[cfg(feature = "nostr-shadow")]
mod roaming;
mod worker;

use std::sync::Arc;

use sqlx::PgPool;

use crate::config::Settings;

pub use repo::transport_queue_status;

pub fn spawn_workers(settings: Arc<Settings>, db: PgPool) {
    worker::spawn_nostr_worker(settings.clone(), db.clone());
    worker::spawn_roaming_worker(settings.clone(), db.clone());
    worker::spawn_ring_worker(settings, db);
}

#[cfg(feature = "nostr-shadow")]
mod roaming_history;
