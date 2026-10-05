use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use p2p_planner_backend::{
    app::build_app,
    config::{
        AppSettings, AuthSettings, DatabaseSettings, HttpSettings, LogFormat, Settings,
        TransportSettings,
    },
    state::AppState,
};
use serde_json::{json, Value};
use sqlx::{migrate::Migrator, PgPool};
use tower::ServiceExt;
use uuid::Uuid;

static MIGRATOR: Migrator = sqlx::migrate!();

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
        transports: TransportSettings::default(),
    }
}

async fn setup() -> anyhow::Result<(PgPool, axum::Router)> {
    dotenvy::dotenv().ok();

    let database_url = std::env::var("TEST_DATABASE_URL")
        .or_else(|_| std::env::var("DATABASE_URL"))
        .or_else(|_| Settings::load().map(|s| s.database.url))
        .expect("TEST_DATABASE_URL, DATABASE_URL, or DATABASE__URL via Settings::load must be set for smoke tests");

    let settings = test_settings(database_url.clone());
    let pool = PgPool::connect(&database_url).await?;
    MIGRATOR.run(&pool).await?;

    let app = build_app(AppState::new(settings, pool.clone()));
    Ok((pool, app))
}

async fn seed_user(pool: &PgPool, email: &str, display_name: &str) -> anyhow::Result<Uuid> {
    let user_id = Uuid::now_v7();
    sqlx::query(
        r#"
        insert into users (id, email, display_name)
        values ($1, $2, $3)
        on conflict do nothing
        "#,
    )
    .bind(user_id)
    .bind(email)
    .bind(display_name)
    .execute(pool)
    .await?;
    Ok(user_id)
}

async fn json_response(response: axum::response::Response) -> Value {
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap();
    assert!(status.is_success(), "status={status}, body={value}");
    value
}

async fn request_json(
    app: &mut axum::Router,
    method: &str,
    path: &str,
    actor_user_id: Uuid,
    body: Value,
) -> Value {
    let request = Request::builder()
        .method(method)
        .uri(path)
        .header("content-type", "application/json")
        .header("x-user-id", actor_user_id.to_string())
        .body(Body::from(body.to_string()))
        .unwrap();

    let response = app.clone().oneshot(request).await.unwrap();
    json_response(response).await
}

async fn request_empty(
    app: &mut axum::Router,
    method: &str,
    path: &str,
    actor_user_id: Uuid,
) -> Value {
    let request = Request::builder()
        .method(method)
        .uri(path)
        .header("x-user-id", actor_user_id.to_string())
        .body(Body::empty())
        .unwrap();

    let response = app.clone().oneshot(request).await.unwrap();
    json_response(response).await
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL or DATABASE_URL pointing to PostgreSQL"]
async fn core_crud_smoke_flow() -> anyhow::Result<()> {
    let (pool, mut app) = setup().await?;
    let actor = seed_user(
        &pool,
        &format!("owner-{}@example.com", Uuid::now_v7()),
        "Owner",
    )
    .await?;

    let workspace = request_json(
        &mut app,
        "POST",
        "/api/v1/workspaces",
        actor,
        json!({"name": "Smoke Workspace", "visibility": "private"}),
    )
    .await;
    let workspace_id = workspace["data"]["id"].as_str().unwrap().to_string();

    let board = request_json(
        &mut app,
        "POST",
        &format!("/api/v1/workspaces/{workspace_id}/boards"),
        actor,
        json!({"name": "Smoke Board", "boardType": "kanban"}),
    )
    .await;
    let board_id = board["data"]["id"].as_str().unwrap().to_string();

    let column = request_json(
        &mut app,
        "POST",
        &format!("/api/v1/boards/{board_id}/columns"),
        actor,
        json!({"name": "Todo"}),
    )
    .await;
    let column_id = column["data"]["id"].as_str().unwrap().to_string();

    let card = request_json(
        &mut app,
        "POST",
        &format!("/api/v1/boards/{board_id}/cards"),
        actor,
        json!({"title": "First card", "columnId": column_id}),
    )
    .await;
    let card_id = card["data"]["id"].as_str().unwrap().to_string();

    let moved = request_json(
        &mut app,
        "POST",
        &format!("/api/v1/cards/{card_id}/move"),
        actor,
        json!({"targetColumnId": column["data"]["id"], "position": 2048.0}),
    )
    .await;
    assert_eq!(moved["data"]["position"], json!(2048.0));

    let archived = request_empty(
        &mut app,
        "POST",
        &format!("/api/v1/cards/{card_id}/archive"),
        actor,
    )
    .await;
    assert_eq!(archived["data"]["isArchived"], Value::Bool(true));

    let unarchived = request_empty(
        &mut app,
        "POST",
        &format!("/api/v1/cards/{card_id}/unarchive"),
        actor,
    )
    .await;
    assert_eq!(unarchived["data"]["isArchived"], Value::Bool(false));

    let updated = request_json(
        &mut app,
        "PATCH",
        &format!("/api/v1/cards/{card_id}"),
        actor,
        json!({"title": "Renamed card", "priority": "high"}),
    )
    .await;
    assert_eq!(
        updated["data"]["title"],
        Value::String("Renamed card".to_string())
    );

    let _hidden_card = request_empty(
        &mut app,
        "POST",
        &format!("/api/v1/cards/{card_id}/hide-local"),
        actor,
    )
    .await;
    let visible_cards = request_empty(
        &mut app,
        "GET",
        &format!("/api/v1/boards/{board_id}/cards"),
        actor,
    )
    .await;
    assert_eq!(visible_cards["data"]["items"], json!([]));
    let hidden_cards = request_empty(
        &mut app,
        "GET",
        &format!("/api/v1/boards/{board_id}/cards?localVisibility=hidden"),
        actor,
    )
    .await;
    assert_eq!(hidden_cards["data"]["items"][0]["id"], card_id);
    let _restored_visibility = request_empty(
        &mut app,
        "DELETE",
        &format!("/api/v1/cards/{card_id}/hide-local"),
        actor,
    )
    .await;
    let _deleted_card = request_empty(
        &mut app,
        "DELETE",
        &format!("/api/v1/cards/{card_id}?scope=all_devices"),
        actor,
    )
    .await;
    let has_tombstone = sqlx::query_scalar::<_, bool>(
        "select exists(select 1 from tombstones where entity_type = 'card' and entity_id = $1)",
    )
    .bind(Uuid::parse_str(&card_id)?)
    .fetch_one(&pool)
    .await?;
    assert!(has_tombstone);
    let _deleted_column = request_empty(
        &mut app,
        "DELETE",
        &format!("/api/v1/columns/{column_id}"),
        actor,
    )
    .await;
    let _deleted_board = request_empty(
        &mut app,
        "DELETE",
        &format!("/api/v1/boards/{board_id}"),
        actor,
    )
    .await;
    let _deleted_workspace = request_empty(
        &mut app,
        "DELETE",
        &format!("/api/v1/workspaces/{workspace_id}"),
        actor,
    )
    .await;

    Ok(())
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL or DATABASE_URL pointing to PostgreSQL"]
async fn workspace_members_smoke_flow() -> anyhow::Result<()> {
    let (pool, mut app) = setup().await?;
    let owner = seed_user(
        &pool,
        &format!("owner-{}@example.com", Uuid::now_v7()),
        "Owner",
    )
    .await?;
    let member = seed_user(
        &pool,
        &format!("member-{}@example.com", Uuid::now_v7()),
        "Member",
    )
    .await?;

    let workspace = request_json(
        &mut app,
        "POST",
        "/api/v1/workspaces",
        owner,
        json!({"name": "Members Workspace"}),
    )
    .await;
    let workspace_id = workspace["data"]["id"].as_str().unwrap().to_string();

    let created_member = request_json(
        &mut app,
        "POST",
        &format!("/api/v1/workspaces/{workspace_id}/members"),
        owner,
        json!({"userId": member, "role": "member"}),
    )
    .await;
    let member_id = created_member["data"]["id"].as_str().unwrap().to_string();

    let updated_member = request_json(
        &mut app,
        "PATCH",
        &format!("/api/v1/workspaces/{workspace_id}/members/{member_id}"),
        owner,
        json!({"role": "admin"}),
    )
    .await;
    assert_eq!(
        updated_member["data"]["role"],
        Value::String("admin".to_string())
    );

    let listed = request_empty(
        &mut app,
        "GET",
        &format!("/api/v1/workspaces/{workspace_id}/members"),
        owner,
    )
    .await;
    assert_eq!(listed["data"]["items"].as_array().unwrap().len(), 2);

    let removed = request_empty(
        &mut app,
        "DELETE",
        &format!("/api/v1/workspaces/{workspace_id}/members/{member_id}"),
        owner,
    )
    .await;
    assert_eq!(
        removed["data"]["status"],
        Value::String("removed".to_string())
    );

    Ok(())
}

#[tokio::test]
async fn health_endpoint_is_still_wired() {
    let request = Request::builder()
        .method("GET")
        .uri("/health")
        .body(Body::empty())
        .unwrap();

    let settings = test_settings("postgres://unused".to_string());
    let pool = PgPool::connect_lazy("postgres://postgres:postgres@localhost/p2p_planner").unwrap();
    let app = build_app(AppState::new(settings, pool));
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
}
