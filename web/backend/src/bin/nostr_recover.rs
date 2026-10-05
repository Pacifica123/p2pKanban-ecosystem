#[cfg(feature = "nostr-shadow")]
use std::{env, path::PathBuf, time::Duration};

#[cfg(feature = "nostr-shadow")]
use anyhow::{bail, Context};
#[cfg(feature = "nostr-shadow")]
use p2p_kanban_nostr_transport::{NostrTransport, NostrTransportConfig};
#[cfg(feature = "nostr-shadow")]
use p2p_planner_backend::config::Settings;
#[cfg(feature = "nostr-shadow")]
use uuid::Uuid;

#[cfg(feature = "nostr-shadow")]
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut args = env::args_os().skip(1);
    let workspace_id = args
        .next()
        .and_then(|value| value.into_string().ok())
        .context("usage: nostr_recover <workspace-uuid> <output.json>")?;
    let output = args
        .next()
        .map(PathBuf::from)
        .context("usage: nostr_recover <workspace-uuid> <output.json>")?;
    if args.next().is_some() {
        bail!("usage: nostr_recover <workspace-uuid> <output.json>");
    }
    Uuid::parse_str(&workspace_id).context("workspace id must be a UUID")?;

    let settings = Settings::load().context("failed to load backend settings")?;
    if !settings.transports.nostr.enabled {
        bail!("Nostr shadow transport must be enabled in runtime configuration");
    }
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

    let envelopes = transport.recover_workspace(&workspace_id).await?;
    let bytes = serde_json::to_vec_pretty(&envelopes)?;
    std::fs::write(&output, bytes)
        .with_context(|| format!("could not write {}", output.display()))?;
    transport.shutdown().await;

    println!(
        "Recovered {} unique envelopes for workspace {} into {}",
        envelopes.len(),
        workspace_id,
        output.display()
    );
    Ok(())
}

#[cfg(not(feature = "nostr-shadow"))]
fn main() {
    eprintln!("This binary requires the backend feature `nostr-shadow`.");
    std::process::exit(2);
}
