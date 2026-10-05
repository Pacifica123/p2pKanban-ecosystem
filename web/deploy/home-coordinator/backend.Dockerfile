FROM rust:1.88-bookworm AS builder

WORKDIR /source
COPY backend ./backend
RUN cargo build --manifest-path backend/Cargo.toml --release --bin p2p-planner-backend

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /source/backend/target/release/p2p-planner-backend /usr/local/bin/p2p-planner-backend
COPY backend/config ./config

ENV APP__HOST=0.0.0.0
ENV APP__PORT=18080
EXPOSE 18080

ENTRYPOINT ["/usr/local/bin/p2p-planner-backend"]
