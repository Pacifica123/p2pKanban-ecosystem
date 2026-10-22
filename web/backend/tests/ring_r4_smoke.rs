//! R4 of the device ring on a real database: a meeting by QR in both modes,
//! with the phone played by the test through the in-memory mailbox
//! (`--features test-memory-relay`, relay `wss://memory.invalid`).
//!
//! TEST_DATABASE_URL=… cargo test --features test-memory-relay --test ring_r4_smoke -- --ignored
#![cfg(feature = "test-memory-relay")]
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use p2p_kanban_nostr_transport::{rendezvous as rv, ring};
use p2p_planner_backend::{
    app::build_app,
    config::{
        AppSettings, AuthSettings, DatabaseSettings, HttpSettings, LogFormat, NostrTransportSettings, Settings,
        TransportSettings,
    },
    state::AppState,
};
use serde_json::{json, Value};
use sqlx::{migrate::Migrator, PgPool};
use tower::ServiceExt;
use uuid::Uuid;

static MIGRATOR: Migrator = sqlx::migrate!();
const NODE_SECRET: &str = "0000000000000000000000000000000000000000000000000000000000000a01";
const PHONE_SECRET: &str = "0000000000000000000000000000000000000000000000000000000000000a02";
const LAPTOP_SECRET: &str = "0000000000000000000000000000000000000000000000000000000000000a04";
const INTRUDER_SECRET: &str = "0000000000000000000000000000000000000000000000000000000000000a05";

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
                relays: vec![rv::memory::URL.into()],
                secret_key: Some(NODE_SECRET.into()),
                master_key_base64: Some("AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=".into()),
                fetch_timeout_secs: 1,
                min_relay_acks: 1,
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


const PROTOCOLS: [&str; 4] = [ring::RING, ring::KEYRING, ring::RENDEZVOUS, ring::ROAMING];

fn now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs()
}

fn phone_hello(phone: &ring::DeviceKeys, session: &str, name: &str, ring_info: Value) -> Value {
    json!({"type": "hello", "sessionId": session,
        "device": {"publicKey": phone.public_key().to_hex(), "name": name, "kind": "android"},
        "software": {"direction": "mobile", "version": "2.2.0", "protocols": PROTOCOLS}, "ring": ring_info})
}

fn say(keys: &ring::DeviceKeys, secret: &[u8], message: &Value, expires: u64) {
    rv::memory::post(&rv::mailbox_events(keys, secret, message, now(), expires).unwrap());
}

fn mail(session: &str, secret: &[u8]) -> Vec<rv::Mail> {
    rv::open_mailbox(&rv::memory::fetch(session), secret)
}

async fn new_user(pool: &PgPool, label: &str) -> anyhow::Result<Uuid> {
    let user = Uuid::now_v7();
    sqlx::query("insert into users (id, email, display_name) values ($1, $2, $3)")
        .bind(user).bind(format!("{label}-{user}@example.test")).bind(label).execute(pool).await?;
    Ok(user)
}

async fn trusted(pool: &PgPool, user: Uuid, key: &str) -> anyhow::Result<bool> {
    Ok(sqlx::query_scalar("select exists(select 1 from trusted_device_peers where user_id=$1 and public_key=$2)")
        .bind(user).bind(key).fetch_one(pool).await?)
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL or DATABASE_URL pointing to PostgreSQL"]
async fn rendezvous_invite_and_join_on_the_node() -> anyhow::Result<()> {
    dotenvy::dotenv().ok();
    let database_url = std::env::var("TEST_DATABASE_URL").or_else(|_| std::env::var("DATABASE_URL"))
        .expect("TEST_DATABASE_URL or DATABASE_URL must be set");
    let pool = PgPool::connect(&database_url).await?;
    MIGRATOR.run(&pool).await?;
    let app = build_app(AppState::new(test_settings(database_url), pool.clone()));
    let node = keys(NODE_SECRET).public_key().to_hex();
    let phone = keys(PHONE_SECRET);
    let phone_pk = phone.public_key().to_hex();

    // ---- invite: the node shows a QR, the phone enters the node's ring.
    let owner = new_user(&pool, "invite").await?;
    ok(&app, "POST", "/api/v1/ring/genesis", owner, Some(json!({"name": "Домашний узел"}))).await;
    let shown = ok(&app, "POST", "/api/v1/ring/rendezvous", owner, Some(json!({"mode": "invite"}))).await;
    let qr = rv::qr_decode(shown["qrText"].as_str().unwrap())?;
    assert_eq!((qr["m"].as_str(), qr["k"].as_str(), qr["n"].as_str()), (Some("invite"), Some(node.as_str()), Some("Домашний узел")));
    assert!(qr["x"].as_u64().unwrap() <= now() + 600);
    let secret = ring::unb64url(qr["s"].as_str().unwrap())?;
    let session = rv::session_id(&secret);
    let path = format!("/api/v1/ring/rendezvous/{session}");
    assert_eq!(ok(&app, "GET", &path, owner, None).await["status"], "waiting");

    say(&phone, &secret, &phone_hello(&phone, &session, "Телефон", Value::Null), qr["x"].as_u64().unwrap());
    let review = ok(&app, "GET", &path, owner, None).await;
    assert_eq!(review["status"], "confirm", "{review}");
    assert_eq!(review["code"], rv::confirm_code(&session, &phone_pk), "both screens show the same code");
    assert_eq!((review["peer"]["name"].as_str(), review["peer"]["alreadyMember"].as_bool()), (Some("Телефон"), Some(false)));

    let welcomed = ok(&app, "POST", &format!("{path}/confirm"), owner, Some(json!({"role": "admin"}))).await;
    assert_eq!(welcomed["status"], "welcomed");
    assert_eq!(welcomed["qrText"], Value::Null, "the QR is not shown after the decision");
    let welcome = mail(&session, &secret).into_iter().find(|m| m.message["type"] == "welcome").expect("welcome in the mailbox");
    let joined = rv::verify_welcome(&welcome, &qr, &phone_pk).map_err(|r| anyhow::anyhow!("{r:?}"))?;
    let added = joined["members"].as_array().unwrap().iter().find(|m| m["publicKey"] == phone_pk.as_str()).unwrap().clone();
    assert_eq!((added["role"].as_str(), added["addedBy"].as_str()), (Some("admin"), Some(node.as_str())));
    assert!(trusted(&pool, owner, &phone_pk).await?, "a ring member is a writer of the owner's boards");
    say(&phone, &secret, &json!({"type": "ack", "sessionId": session, "accountId": joined["accountId"], "heads": joined["heads"]}), qr["x"].as_u64().unwrap());
    let done = ok(&app, "GET", &path, owner, None).await;
    assert_eq!(done["status"], "done", "{done}");
    let secret_left: Option<String> = sqlx::query_scalar("select secret_b64 from ring_rendezvous_sessions where session_id=$1").bind(&session).fetch_one(&pool).await?;
    assert_eq!(secret_left, None, "the secret is erased after the meeting");
    let ring_view = ok(&app, "GET", "/api/v1/ring", owner, None).await;
    assert_eq!(ring_view["ring"]["members"].as_array().unwrap().len(), 2);

    // Re-connecting the same phone writes nothing new: welcome is the remote repair.
    let again = ok(&app, "POST", "/api/v1/ring/rendezvous", owner, Some(json!({"mode": "invite"}))).await;
    let qr2 = rv::qr_decode(again["qrText"].as_str().unwrap())?;
    let secret2 = ring::unb64url(qr2["s"].as_str().unwrap())?;
    let session2 = rv::session_id(&secret2);
    say(&phone, &secret2, &phone_hello(&phone, &session2, "Телефон", json!({"accountId": joined["accountId"], "members": 2})), qr2["x"].as_u64().unwrap());
    let path2 = format!("/api/v1/ring/rendezvous/{session2}");
    assert_eq!(ok(&app, "GET", &path2, owner, None).await["peer"]["alreadyMember"], true);
    ok(&app, "POST", &format!("{path2}/confirm"), owner, None).await;
    let entries: i64 = sqlx::query_scalar("select count(*) from account_ring_entries where account_id=$1").bind(joined["accountId"].as_str()).fetch_one(&pool).await?;
    assert_eq!(entries, 2, "genesis and one add");

    // A second device in the same mailbox stops the meeting.
    let contested = ok(&app, "POST", "/api/v1/ring/rendezvous", owner, Some(json!({"mode": "invite"}))).await;
    let qr3 = rv::qr_decode(contested["qrText"].as_str().unwrap())?;
    let secret3 = ring::unb64url(qr3["s"].as_str().unwrap())?;
    let session3 = rv::session_id(&secret3);
    let intruder = keys(INTRUDER_SECRET);
    say(&phone, &secret3, &phone_hello(&phone, &session3, "Телефон", Value::Null), qr3["x"].as_u64().unwrap());
    say(&intruder, &secret3, &phone_hello(&intruder, &session3, "Телефон", Value::Null), qr3["x"].as_u64().unwrap());
    let stopped = ok(&app, "GET", &format!("/api/v1/ring/rendezvous/{session3}"), owner, None).await;
    assert_eq!((stopped["status"].as_str(), stopped["outcome"]["reason"].as_str()), (Some("refused"), Some("contested")), "{stopped}");
    assert!(mail(&session3, &secret3).iter().any(|m| m.sender == node && m.message["reason"] == "contested"), "both sides see why");

    // A device of another ring with other members is a merge, not an add.
    let merge = ok(&app, "POST", "/api/v1/ring/rendezvous", owner, Some(json!({"mode": "invite"}))).await;
    let qr4 = rv::qr_decode(merge["qrText"].as_str().unwrap())?;
    let secret4 = ring::unb64url(qr4["s"].as_str().unwrap())?;
    let session4 = rv::session_id(&secret4);
    let laptop = keys(LAPTOP_SECRET);
    say(&laptop, &secret4, &phone_hello(&laptop, &session4, "Рабочий ноутбук", json!({"accountId": "ab".repeat(32), "members": 3})), qr4["x"].as_u64().unwrap());
    let refused = ok(&app, "GET", &format!("/api/v1/ring/rendezvous/{session4}"), owner, None).await;
    assert_eq!(refused["outcome"]["reason"], "ring-merge-unsupported", "{refused}");
    assert!(!trusted(&pool, owner, &laptop.public_key().to_hex()).await?);

    // ---- join: the node shows a QR, a phone from its own ring adds the node.
    let joiner = new_user(&pool, "join").await?;
    let lone = ok(&app, "POST", "/api/v1/ring/genesis", joiner, Some(json!({"name": "Ноутбук-узел"}))).await;
    let lone_account = lone["ring"]["accountId"].as_str().unwrap().to_string();
    let shown = ok(&app, "POST", "/api/v1/ring/rendezvous", joiner, Some(json!({"mode": "join"}))).await;
    let qr = rv::qr_decode(shown["qrText"].as_str().unwrap())?;
    let secret = ring::unb64url(qr["s"].as_str().unwrap())?;
    let session = rv::session_id(&secret);
    assert_eq!(shown["code"], rv::confirm_code(&session, &node), "the joiner shows its code at once");
    let mails = mail(&session, &secret);
    assert_eq!(mails.len(), 1, "hello is in the mailbox before the scan");
    assert_eq!(mails[0].message["ring"], json!({"accountId": lone_account, "members": 1}));

    // The phone's ring: phone (genesis) and a laptop the node has never seen; a space and a board.
    let genesis = ring::make_entry(&phone, json!({"type": "genesis", "parents": [], "nonce": ring::b64url(Uuid::now_v7().as_bytes()),
        "device": {"publicKey": phone_pk, "name": "Телефон", "kind": "android", "role": "admin"},
        "relays": {"urls": [rv::memory::URL], "minAcks": 1}}).as_object().unwrap().clone(), now() - 100)?;
    let account = genesis["id"].as_str().unwrap().to_string();
    let add_laptop = ring::make_entry(&phone, json!({"type": "add", "accountId": account, "parents": [account], "via": "rendezvous",
        "device": {"publicKey": laptop.public_key().to_hex(), "name": "Ноутбук", "kind": "arch", "role": "admin"}}).as_object().unwrap().clone(), now() - 50)?;
    let state = ring::fold_ring(&[genesis.clone(), add_laptop.clone()], Some(&account))?;
    let hello = rv::sponsor_review(&qr, &mails, &phone_pk, &state, true, now()).map_err(|r| anyhow::anyhow!("{r:?}"))?.expect("hello");
    let add_node = ring::make_entry(&phone, json!({"type": "add", "accountId": account, "parents": [add_laptop["id"]], "via": "rendezvous",
        "device": {"publicKey": node, "name": hello["device"]["name"], "kind": "web", "role": "admin"}}).as_object().unwrap().clone(), now())?;
    let entries = vec![genesis, add_laptop, add_node.clone()];
    // Fresh ids: the database outlives a test run.
    let space = Uuid::now_v7().to_string();
    let board = Uuid::now_v7().to_string();
    let board_key = ring::b64url(&[7u8; 32]);
    let keyring = json!({"protocol": ring::KEYRING, "accountId": account, "ringHeads": [add_node["id"]], "items": [
        {"kind": "space", "id": space, "name": "Поездка", "rev": 1, "updatedBy": phone_pk, "deleted": false},
        {"kind": "board", "id": board, "spaceId": space, "name": "Маршрут", "rev": 1, "updatedBy": phone_pk, "deleted": false,
         "roaming": {"protocol": ring::ROAMING, "epoch": 1, "boardKey": board_key}}]});
    say(&phone, &secret, &json!({"type": "welcome", "sessionId": session, "accountId": account, "entries": entries, "keyring": keyring}), qr["x"].as_u64().unwrap());

    let done = ok(&app, "GET", &format!("/api/v1/ring/rendezvous/{session}"), joiner, None).await;
    assert_eq!(done["status"], "done", "{done}");
    assert_eq!(done["outcome"]["members"], 3);
    let ack = mail(&session, &secret).into_iter().find(|m| m.message["type"] == "ack").expect("ack to the phone");
    assert_eq!((ack.sender.as_str(), &ack.message["accountId"]), (node.as_str(), &json!(account)));
    let now_ring: String = sqlx::query_scalar("select account_id from account_rings where user_id=$1").bind(joiner).fetch_one(&pool).await?;
    assert_eq!(now_ring, account, "the lone ring is replaced by the phone's ring");
    let old_left: i64 = sqlx::query_scalar("select count(*) from account_ring_entries where account_id=$1").bind(&lone_account).fetch_one(&pool).await?;
    assert_eq!(old_left, 0);
    assert!(trusted(&pool, joiner, &phone_pk).await? && trusted(&pool, joiner, &laptop.public_key().to_hex()).await?,
        "every member of the ring, also the laptop the node never saw, writes the boards");
    let adopted: (String, String) = sqlx::query_as("select b.name, w.name from boards b join workspaces w on w.id=b.workspace_id where b.id=$1::uuid and w.owner_user_id=$2")
        .bind(&board).bind(joiner).fetch_one(&pool).await?;
    assert_eq!(adopted, ("Маршрут".to_string(), "Поездка".to_string()), "the phone's board is now on the node");
    let key_here: String = sqlx::query_scalar("select board_key_base64 from roaming_board_capabilities where board_id=$1::uuid").bind(&board).fetch_one(&pool).await?;
    assert_eq!(key_here, board_key);

    // A node already in a ring with others is not merged by a join.
    let busy = ok(&app, "POST", "/api/v1/ring/rendezvous", joiner, Some(json!({"mode": "join"}))).await;
    assert_eq!(rv::open_mailbox(&rv::memory::fetch(&rv::session_id(&ring::unb64url(rv::qr_decode(busy["qrText"].as_str().unwrap())?["s"].as_str().unwrap())?)),
        &ring::unb64url(rv::qr_decode(busy["qrText"].as_str().unwrap())?["s"].as_str().unwrap())?)[0].message["ring"]["members"], 3,
        "the hello tells a sponsor of another ring that this is a merge");
    let canceled = ok(&app, "POST", &format!("/api/v1/ring/rendezvous/{}/cancel", busy["sessionId"].as_str().unwrap()), joiner, None).await;
    assert_eq!(canceled["status"], "canceled");
    Ok(())
}
