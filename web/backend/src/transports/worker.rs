use std::{sync::Arc, time::Duration};

use sqlx::PgPool;

use crate::config::Settings;

#[cfg(feature = "nostr-shadow")]
pub fn spawn_nostr_worker(settings: Arc<Settings>, db: PgPool) {
    if !settings.transports.nostr.enabled {
        tracing::info!("Nostr shadow transport is disabled");
        return;
    }

    tokio::spawn(async move {
        if let Err(error) = run_nostr_worker(settings, db).await {
            tracing::error!(error = %error, "Nostr shadow worker stopped");
        }
    });
}

#[cfg(not(feature = "nostr-shadow"))]
pub fn spawn_nostr_worker(settings: Arc<Settings>, _db: PgPool) {
    if settings.transports.nostr.enabled {
        tracing::error!("Nostr shadow transport requested but backend feature is disabled");
    }
}

#[cfg(feature = "nostr-shadow")]
pub fn spawn_roaming_worker(settings: Arc<Settings>, db: PgPool) {
    if !settings.transports.nostr.enabled {
        return;
    }
    tokio::spawn(async move {
        // Startup DB/relay errors must not disable replication until process restart.
        loop {
            if let Err(error) = super::roaming::run(settings.clone(), db.clone()).await {
                tracing::warn!(error = %error, "roaming worker will retry in 5 seconds");
            }
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    });
}

#[cfg(not(feature = "nostr-shadow"))]
pub fn spawn_roaming_worker(_settings: Arc<Settings>, _db: PgPool) {}

#[cfg(feature = "nostr-shadow")]
async fn run_nostr_worker(settings: Arc<Settings>, db: PgPool) -> anyhow::Result<()> {
    use p2p_kanban_nostr_transport::{NostrTransport, NostrTransportConfig};

    let nostr = &settings.transports.nostr;
    let transport = NostrTransport::connect(NostrTransportConfig {
        relays: nostr.relays.clone(),
        secret_key: nostr.secret_key.clone().unwrap_or_default(),
        master_key: nostr.master_key()?,
        event_kind: nostr.event_kind,
        fetch_timeout: Duration::from_secs(nostr.fetch_timeout_secs),
        min_relay_acks: nostr.min_relay_acks,
    })
    .await?;

    if nostr.backfill_on_start {
        let queued = super::repo::enqueue_nostr_backfill(&db).await?;
        tracing::info!(
            queued,
            "queued existing sync events for Nostr shadow backfill"
        );
    }

    let poll = Duration::from_millis(settings.transports.worker_poll_interval_ms);
    loop {
        let batch = match super::repo::claim_nostr_batch(
            &db,
            settings.transports.batch_size,
            settings.transports.max_attempts,
        )
        .await
        {
            Ok(batch) => batch,
            Err(error) => {
                tracing::warn!(error = %error, "could not claim Nostr shadow outbox batch");
                tokio::time::sleep(poll).await;
                continue;
            }
        };

        if batch.is_empty() {
            tokio::time::sleep(poll).await;
            continue;
        }

        for item in batch {
            match transport.publish(item.envelope).await {
                Ok(receipt) => {
                    if let Err(error) =
                        super::repo::mark_delivered(&db, item.outbox_id, &receipt.nostr_event_id)
                            .await
                    {
                        tracing::warn!(
                            outbox_id = %item.outbox_id,
                            error = %error,
                            "Nostr event was published but outbox receipt was not persisted"
                        );
                    }
                }
                Err(error) => {
                    tracing::warn!(
                        outbox_id = %item.outbox_id,
                        error = %error,
                        "Nostr shadow publish failed"
                    );
                    if let Err(mark_error) = super::repo::mark_failed(
                        &db,
                        item.outbox_id,
                        &format!("{error:#}"),
                        settings.transports.max_attempts,
                    )
                    .await
                    {
                        tracing::error!(
                            outbox_id = %item.outbox_id,
                            error = %mark_error,
                            "could not persist Nostr shadow failure"
                        );
                    }
                }
            }
        }
    }
}
