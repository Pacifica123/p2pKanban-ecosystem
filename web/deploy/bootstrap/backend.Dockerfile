# syntax=docker/dockerfile:1.7

FROM rust:1.88-bookworm AS builder

WORKDIR /source
COPY backend ./backend
RUN cargo build \
    --manifest-path backend/Cargo.toml \
    --locked \
    --release \
    --bin p2p-planner-backend

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /source/backend/target/release/p2p-planner-backend /usr/local/bin/p2p-planner-backend
COPY backend/config ./config
COPY deploy/bootstrap/backend-entrypoint.sh /usr/local/bin/p2pkanban-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/p2pkanban-entrypoint \
    && chmod 0555 /usr/local/bin/p2pkanban-entrypoint

EXPOSE 18080
ENTRYPOINT ["/usr/local/bin/p2pkanban-entrypoint"]
