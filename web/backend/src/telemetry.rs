use crate::config::LogFormat;
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

pub fn init_tracing(log_format: LogFormat) {
    let env_filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info,tower_http=info,sqlx=warn"));

    match log_format {
        LogFormat::Pretty => {
            tracing_subscriber::registry()
                .with(env_filter)
                .with(fmt::layer().pretty())
                .init();
        }
        LogFormat::Json => {
            tracing_subscriber::registry()
                .with(env_filter)
                .with(fmt::layer().json())
                .init();
        }
    }
}
