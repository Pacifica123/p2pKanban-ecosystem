//! R2 of the device ring on a real database: genesis, moving existing trust
//! into the ring, the node's keyring copy, and taking in a phone's sealed copies.
//! Relays are unreachable on purpose; the relay leg is covered by the contract
//! vectors in crates/nostr-transport/tests/ring_contract_vectors.rs.
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use p2p_kanban_nostr_transport::ring;
use p2p_planner_backend::{
    app::build_app,
    config::{
        AppSettings, AuthSettings, DatabaseSettings, HttpSettings, LogFormat, NostrTransportSettings, Settings,
        TransportSettings,
    },
    modules::ring::{absorb, Absorbed},
    state::AppState,
};
use serde_json::{json, Value};
use sqlx::{migrate::Migrator, PgPool};
use tower::ServiceExt;
use uuid::Uuid;

static MIGRATOR: Migrator = sqlx::migrate!();
const NODE_SECRET: &str = "0000000000000000000000000000000000000000000000000000000000000a01";
const PHONE_SECRET: &str = "0000000000000000000000000000000000000000000000000000000000000a02";
const OUTSIDER_SECRET: &str = "0000000000000000000000000000000000000000000000000000000000000a03";

fn test_settings(database_url: String) -> Settings {
    Settings {
        app: AppSettings {
            name: "p2p-planner-backend-test".to_string(),
            env: "test".to_string(),
            host: "127.0.0.1".parse().unwrap(),
            port: 0,
            log_format: LogFormat::Pretty,
        },
        database: DatabaseSettings {
            url: database_url,
            max_connections: 5,
            min_connections: 1,
            connect_timeout_secs: 5,
        },
        http: HttpSettings {
            body_limit_mb: 10,
            cors_allowed_origins: vec![
                "http://localhost:3000".to_string(),
                "http://127.0.0.1:3000".to_string(),
                "http://localhost:5173".to_string(),
                "http://127.0.0.1:5173".to_string(),
            ],
        },
        auth: AuthSettings {
            jwt_secret: "test-secret".to_string(),
            previous_jwt_secrets: vec![],
            access_token_ttl_minutes: 15,
            refresh_token_ttl_days: 30,
            public_signup_enabled: true,
            refresh_cookie_name: "p2p_planner_refresh".to_string(),
            device_cookie_name: "p2p_planner_device".to_string(),
            cookie_same_site: p2p_planner_backend::config::CookieSameSite::Lax,
            cookie_secure: false,
            enable_dev_header_auth: true,
            auth_rate_limit_window_secs: 60,
            auth_rate_limit_max_attempts: 20,
            sensitive_rate_limit_window_secs: 60,
            sensitive_rate_limit_max_attempts: 60,
        },
        transports: TransportSettings {
            nostr: NostrTransportSettings {
                enabled: true,
                relays: vec!["wss://127.0.0.1:9/".into(), "wss://127.0.0.1:10/".into(), "ws://127.0.0.1:11/".into()],
                secret_key: Some(NODE_SECRET.into()),
                master_key_base64: Some("AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=".into()),
                fetch_timeout_secs: 1,
                min_relay_acks: 2,
                ..NostrTransportSettings::default()
            },
            ..TransportSettings::default()
        },
    }
}

async fn call(app: &axum::Router, method: &str, path: &str, user: Uuid, body: Option<Value>) -> (StatusCode, Value) {
    let mut request = Request::builder().method(method).uri(path).header("x-user-id", user.to_string());
    if body.is_some() {
        request = request.header("content-type", "application/json");
    }
    let request = request.body(body.map(|b| Body::from(b.to_string())).unwrap_or_else(Body::empty)).unwrap();
    let response = app.clone().oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (status, serde_json::from_slice(&bytes).unwrap_or(Value::Null))
}

async fn ok(app: &axum::Router, method: &str, path: &str, user: Uuid, body: Option<Value>) -> Value {
    let (status, value) = call(app, method, path, user, body).await;
    assert!(status.is_success(), "{method} {path}: {status} {value}");
    value["data"].clone()
}

fn keys(secret: &str) -> ring::DeviceKeys {
    ring::DeviceKeys::parse(secret).unwrap()
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL or DATABASE_URL pointing to PostgreSQL"]
async fn ring_genesis_migration_keyring_and_phone_copies() -> anyhow::Result<()> {
    dotenvy::dotenv().ok();
    let database_url = std::env::var("TEST_DATABASE_URL").or_else(|_| std::env::var("DATABASE_URL"))
        .expect("TEST_DATABASE_URL or DATABASE_URL must be set");
    let pool = PgPool::connect(&database_url).await?;
    MIGRATOR.run(&pool).await?;
    let app = build_app(AppState::new(test_settings(database_url), pool.clone()));

    let user = Uuid::now_v7();
    sqlx::query("insert into users (id, email, display_name) values ($1, $2, 'Кольцо')")
        .bind(user).bind(format!("ring-{user}@example.test")).execute(&pool).await?;
    let node = keys(NODE_SECRET).public_key().to_hex();
    let phone = keys(PHONE_SECRET);
    let phone_pk = phone.public_key().to_hex();
    let outsider = keys(OUTSIDER_SECRET);
    sqlx::query("insert into trusted_device_peers(user_id,public_key) values($1,$2)").bind(user).bind(&phone_pk).execute(&pool).await?;
    let workspace = ok(&app, "POST", "/api/v1/workspaces", user, Some(json!({"name": "Личное", "visibility": "private"}))).await;
    let space_id = workspace["id"].as_str().unwrap().to_string();
    let board = ok(&app, "POST", &format!("/api/v1/workspaces/{space_id}/boards"), user, Some(json!({"name": "Планы", "boardType": "kanban"}))).await;
    let board_id = board["id"].as_str().unwrap().to_string();

    // Before genesis: the phone is trusted the old way and listed as outside the ring.
    let before = ok(&app, "GET", "/api/v1/ring", user, None).await;
    assert_eq!(before["ring"], Value::Null);
    assert_eq!(before["legacy"][0]["publicKey"], phone_pk.as_str());
    assert_eq!(before["relays"]["urls"], json!(["wss://127.0.0.1:9/", "wss://127.0.0.1:10/"]), "ws:// is not a ring relay");

    let created = ok(&app, "POST", "/api/v1/ring/genesis", user, Some(json!({"name": "Домашний узел"}))).await;
    let account = created["ring"]["accountId"].as_str().unwrap().to_string();
    assert_eq!(created["ring"]["members"][0]["publicKey"], node.as_str());
    assert_eq!(created["ring"]["relays"]["minAcks"], 2);
    assert_eq!(call(&app, "POST", "/api/v1/ring/genesis", user, Some(json!({"name": "ещё"}))).await.0, StatusCode::CONFLICT);

    // Only devices the node already trusts can be moved in; the rest wait for QR (R4).
    let stranger = call(&app, "POST", "/api/v1/ring/migrate", user,
        Some(json!({"publicKey": outsider.public_key().to_hex(), "name": "Чужой", "kind": "android"}))).await;
    assert_eq!(stranger.0, StatusCode::FORBIDDEN, "{}", stranger.1);
    let moved = ok(&app, "POST", "/api/v1/ring/migrate", user,
        Some(json!({"publicKey": phone_pk, "name": "Телефон", "kind": "android"}))).await;
    assert_eq!(moved["ring"]["members"].as_array().unwrap().len(), 2);
    assert_eq!(moved["legacy"], json!([]));
    assert_eq!(call(&app, "POST", "/api/v1/ring/migrate", user,
        Some(json!({"publicKey": phone_pk, "name": "Телефон", "kind": "android"}))).await.0, StatusCode::BAD_REQUEST);

    // Sync with unreachable relays still refreshes the keyring and reports why nothing was published.
    let synced = ok(&app, "POST", "/api/v1/ring/sync", user, None).await;
    assert_eq!(synced["lastSync"]["quorum"], false);
    assert!(!synced["lastSync"]["errors"].as_array().unwrap().is_empty() || synced["lastSync"]["published"].as_array().unwrap().iter().all(|p| p["accepted"] == json!([])));
    let items = synced["keyring"]["items"].as_array().unwrap();
    assert!(items.iter().any(|i| i["kind"] == "space" && i["id"] == space_id.as_str() && i["onThisNode"] == true));
    assert!(items.iter().any(|i| i["kind"] == "board" && i["id"] == board_id.as_str() && i["epoch"] == 1));
    assert_eq!(synced["keyring"]["summary"]["boards"], 1);

    // The phone renames itself, publishes its log, a keyring with a space made on the trip, and an old-version presence.
    let ring_now = &synced["ring"];
    let entries: Vec<Value> = sqlx::query_scalar("select event_json from account_ring_entries where account_id=$1").bind(&account).fetch_all(&pool).await?;
    let heads = ring_now["heads"].clone();
    let rename = ring::make_entry(&phone, json!({"type": "rename", "accountId": account, "parents": heads,
        "publicKey": phone_pk, "name": "Телефон в поездке"}).as_object().unwrap().clone(), 1_791_300_000)?;
    let mut log = entries.clone();
    log.push(rename.clone());
    let members = vec![node.clone(), phone_pk.clone()];
    let trip = "01a11100-0000-7000-8000-00000000f001";
    let fetched = vec![
        ring::sealed_event(&phone, "ring-log", &account, &members, &json!({"protocol": ring::RING, "accountId": account, "entries": log}), 1_791_300_001)?,
        ring::sealed_event(&phone, "keyring", &account, &members, &json!({"protocol": ring::KEYRING, "accountId": account, "ringHeads": [rename["id"]],
            "items": [{"kind": "space", "id": trip, "name": "Поездка", "rev": 1, "updatedBy": phone_pk, "deleted": false}]}), 1_791_300_002)?,
        ring::sealed_event(&phone, "presence", &account, &members, &json!({"protocol": ring::RING, "type": "presence", "accountId": account,
            "publicKey": phone_pk, "seenAt": 1_791_300_003, "software": {"direction": "mobile", "version": "2.1.0", "protocols": [ring::ROAMING]},
            "ringHeads": heads, "keyring": null, "relays": []}), 1_791_300_003)?,
        // Sealed for the phone only: the node cannot open it and does not need to.
        ring::sealed_event(&phone, "keyring", &account, &[phone_pk.clone()], &json!({"protocol": ring::KEYRING, "accountId": account, "ringHeads": [], "items": []}), 1_791_300_004)?,
        // An outsider's keyring is opened but not accepted.
        ring::sealed_event(&outsider, "keyring", &account, &members, &json!({"protocol": ring::KEYRING, "accountId": account, "ringHeads": [],
            "items": [{"kind": "space", "id": "01a11100-0000-7000-8000-00000000bad0", "name": "Подброшено", "rev": 9, "updatedBy": outsider.public_key().to_hex(), "deleted": false}]}), 1_791_300_005)?,
    ];
    let (absorbed, state) = absorb(&pool, &keys(NODE_SECRET), &account, &fetched).await?;
    assert_eq!(absorbed, Absorbed { not_for_this_node: 1, new_entries: 1, keyring_copies: 1, presences: 1 });
    assert_eq!(state["heads"], json!([rename["id"]]));
    assert_eq!(absorb(&pool, &keys(NODE_SECRET), &account, &fetched).await?.0, Absorbed { not_for_this_node: 1, ..Absorbed::default() }, "idempotent");

    let after = ok(&app, "GET", "/api/v1/ring", user, None).await;
    let phone_member = after["ring"]["members"].as_array().unwrap().iter().find(|m| m["publicKey"] == phone_pk.as_str()).unwrap().clone();
    assert_eq!(phone_member["name"], "Телефон в поездке");
    let items = after["keyring"]["items"].as_array().unwrap();
    assert!(items.iter().any(|i| i["id"] == trip && i["onThisNode"] == false), "the trip space reached the node");
    assert!(!items.iter().any(|i| i["name"] == "Подброшено"));
    assert_eq!(after["skew"], json!([{"publicKey": phone_pk, "missingProtocols": [ring::RING, ring::KEYRING, ring::RENDEZVOUS], "staleRing": true}]));
    Ok(())
}
