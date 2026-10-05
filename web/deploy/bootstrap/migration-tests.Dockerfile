FROM rust:1.88-bookworm
WORKDIR /source
COPY backend ./backend
RUN cargo test --locked --manifest-path backend/Cargo.toml --lib db::migrations
CMD ["cargo", "test", "--locked", "--manifest-path", "backend/Cargo.toml", "--lib", "db::migrations::tests::postgres_history_and_data_survive_portable_restart", "--", "--ignored", "--nocapture"]
