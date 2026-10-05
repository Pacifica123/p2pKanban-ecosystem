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

async fn json_response(response: axum::response::Response, expected_status: StatusCode) -> Value {
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap_or_else(|_| json!({}));
    assert_eq!(status, expected_status, "status={status}, body={value}");
    value
}

async fn request(
    app: &axum::Router,
    method: &str,
    path: &str,
    actor_user_id: Uuid,
    body: Option<Value>,
    expected_status: StatusCode,
) -> Value {
    let mut builder = Request::builder()
        .method(method)
        .uri(path)
        .header("x-user-id", actor_user_id.to_string());

    let request = if let Some(body) = body {
        builder = builder.header("content-type", "application/json");
        builder.body(Body::from(body.to_string())).unwrap()
    } else {
        builder.body(Body::empty()).unwrap()
    };

    let response = app.clone().oneshot(request).await.unwrap();
    json_response(response, expected_status).await
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL or DATABASE_URL pointing to PostgreSQL"]
async fn appearance_defaults_and_updates_work() -> anyhow::Result<()> {
    let (pool, app) = setup().await?;
    let owner = seed_user(
        &pool,
        &format!("owner-{}@example.com", Uuid::now_v7()),
        "Owner",
    )
    .await?;

    let workspace = request(
        &app,
        "POST",
        "/api/v1/workspaces",
        owner,
        Some(json!({"name": "Appearance Workspace", "visibility": "private"})),
        StatusCode::CREATED,
    )
    .await;
    let workspace_id = workspace["data"]["id"].as_str().unwrap().to_string();

    let board = request(
        &app,
        "POST",
        &format!("/api/v1/workspaces/{workspace_id}/boards"),
        owner,
        Some(json!({"name": "Appearance Board", "boardType": "kanban"})),
        StatusCode::CREATED,
    )
    .await;
    let board_id = board["data"]["id"].as_str().unwrap().to_string();

    let me_default = request(
        &app,
        "GET",
        "/api/v1/me/appearance",
        owner,
        None,
        StatusCode::OK,
    )
    .await;
    assert_eq!(me_default["data"]["isCustomized"], json!(false));
    assert_eq!(me_default["data"]["appTheme"], json!("system"));
    assert_eq!(me_default["data"]["density"], json!("comfortable"));
    assert_eq!(me_default["data"]["reduceMotion"], json!(false));
    assert_eq!(
        me_default["data"]["checklistItemSubmitMode"],
        json!("ctrl_enter")
    );
    assert_eq!(me_default["data"]["cardDetailsMode"], json!("drawer"));

    let me_updated = request(
        &app,
        "PUT",
        "/api/v1/me/appearance",
        owner,
        Some(json!({
            "appTheme": "dark",
            "density": "compact",
            "reduceMotion": true,
            "checklistItemSubmitMode": "enter",
            "cardDetailsMode": "modal"
        })),
        StatusCode::OK,
    )
    .await;
    assert_eq!(me_updated["data"]["isCustomized"], json!(true));
    assert_eq!(me_updated["data"]["appTheme"], json!("dark"));
    assert_eq!(me_updated["data"]["density"], json!("compact"));
    assert_eq!(me_updated["data"]["reduceMotion"], json!(true));
    assert_eq!(
        me_updated["data"]["checklistItemSubmitMode"],
        json!("enter")
    );
    assert_eq!(me_updated["data"]["cardDetailsMode"], json!("modal"));

    let board_default = request(
        &app,
        "GET",
        &format!("/api/v1/boards/{board_id}/appearance"),
        owner,
        None,
        StatusCode::OK,
    )
    .await;
    assert_eq!(board_default["data"]["isCustomized"], json!(false));
    assert_eq!(board_default["data"]["themePreset"], json!("system"));
    assert_eq!(board_default["data"]["wallpaper"]["kind"], json!("none"));
    assert_eq!(board_default["data"]["wallpaper"]["value"], Value::Null);
    assert_eq!(board_default["data"]["columnDensity"], json!("comfortable"));
    assert_eq!(board_default["data"]["cardPreviewMode"], json!("expanded"));
    assert_eq!(board_default["data"]["showCardDescription"], json!(true));
    assert_eq!(board_default["data"]["showCardDates"], json!(true));
    assert_eq!(board_default["data"]["showChecklistProgress"], json!(true));
    assert_eq!(board_default["data"]["customProperties"], json!({}));

    let board_updated = request(
        &app,
        "PUT",
        &format!("/api/v1/boards/{board_id}/appearance"),
        owner,
        Some(json!({
            "themePreset": "midnight-blue",
            "wallpaper": {"kind": "accent"},
            "columnDensity": "compact",
            "cardPreviewMode": "compact",
            "showCardDescription": false,
            "showCardDates": false,
            "showChecklistProgress": false,
            "customProperties": {"accentColor": "#a855f7", "columnHeaderStyle": "flat"}
        })),
        StatusCode::OK,
    )
    .await;
    assert_eq!(board_updated["data"]["isCustomized"], json!(true));
    assert_eq!(board_updated["data"]["themePreset"], json!("midnight-blue"));
    assert_eq!(board_updated["data"]["wallpaper"]["kind"], json!("accent"));
    assert_eq!(board_updated["data"]["wallpaper"]["value"], Value::Null);
    assert_eq!(board_updated["data"]["columnDensity"], json!("compact"));
    assert_eq!(board_updated["data"]["cardPreviewMode"], json!("compact"));
    assert_eq!(board_updated["data"]["showCardDescription"], json!(false));
    assert_eq!(board_updated["data"]["showCardDates"], json!(false));
    assert_eq!(board_updated["data"]["showChecklistProgress"], json!(false));
    assert_eq!(
        board_updated["data"]["customProperties"],
        json!({"accentColor": "#a855f7", "columnHeaderStyle": "flat"})
    );

    let board_partial = request(
        &app,
        "PUT",
        &format!("/api/v1/boards/{board_id}/appearance"),
        owner,
        Some(json!({"cardPreviewMode": "expanded", "showCardDates": true})),
        StatusCode::OK,
    )
    .await;
    assert_eq!(board_partial["data"]["themePreset"], json!("midnight-blue"));
    assert_eq!(board_partial["data"]["wallpaper"]["kind"], json!("accent"));
    assert_eq!(board_partial["data"]["wallpaper"]["value"], Value::Null);
    assert_eq!(board_partial["data"]["columnDensity"], json!("compact"));
    assert_eq!(board_partial["data"]["cardPreviewMode"], json!("expanded"));
    assert_eq!(board_partial["data"]["showCardDescription"], json!(false));
    assert_eq!(board_partial["data"]["showCardDates"], json!(true));
    assert_eq!(board_partial["data"]["showChecklistProgress"], json!(false));
    assert_eq!(
        board_partial["data"]["customProperties"],
        json!({"accentColor": "#a855f7", "columnHeaderStyle": "flat"})
    );

    Ok(())
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL or DATABASE_URL pointing to PostgreSQL"]
async fn appearance_validation_and_permissions_are_enforced() -> anyhow::Result<()> {
    let (pool, app) = setup().await?;
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
    let outsider = seed_user(
        &pool,
        &format!("outsider-{}@example.com", Uuid::now_v7()),
        "Outsider",
    )
    .await?;

    let workspace = request(
        &app,
        "POST",
        "/api/v1/workspaces",
        owner,
        Some(json!({"name": "Permissions Workspace", "visibility": "private"})),
        StatusCode::CREATED,
    )
    .await;
    let workspace_id = workspace["data"]["id"].as_str().unwrap().to_string();

    let board = request(
        &app,
        "POST",
        &format!("/api/v1/workspaces/{workspace_id}/boards"),
        owner,
        Some(json!({"name": "Permissions Board", "boardType": "kanban"})),
        StatusCode::CREATED,
    )
    .await;
    let board_id = board["data"]["id"].as_str().unwrap().to_string();

    let _member_added = request(
        &app,
        "POST",
        &format!("/api/v1/workspaces/{workspace_id}/members"),
        owner,
        Some(json!({"userId": member, "role": "member"})),
        StatusCode::CREATED,
    )
    .await;

    let member_can_read = request(
        &app,
        "GET",
        &format!("/api/v1/boards/{board_id}/appearance"),
        member,
        None,
        StatusCode::OK,
    )
    .await;
    assert_eq!(member_can_read["data"]["boardId"], json!(board_id));

    let member_cannot_write = request(
        &app,
        "PUT",
        &format!("/api/v1/boards/{board_id}/appearance"),
        member,
        Some(json!({"themePreset": "member-write-attempt"})),
        StatusCode::FORBIDDEN,
    )
    .await;
    assert_eq!(member_cannot_write["error"]["code"], json!("forbidden"));

    let outsider_cannot_read = request(
        &app,
        "GET",
        &format!("/api/v1/boards/{board_id}/appearance"),
        outsider,
        None,
        StatusCode::FORBIDDEN,
    )
    .await;
    assert_eq!(outsider_cannot_read["error"]["code"], json!("forbidden"));

    let invalid_theme = request(
        &app,
        "PUT",
        "/api/v1/me/appearance",
        owner,
        Some(json!({"appTheme": "neon"})),
        StatusCode::BAD_REQUEST,
    )
    .await;
    assert_eq!(invalid_theme["error"]["code"], json!("bad_request"));
    assert_eq!(
        invalid_theme["error"]["message"],
        json!("appTheme has unsupported value")
    );

    let invalid_checklist_mode = request(
        &app,
        "PUT",
        "/api/v1/me/appearance",
        owner,
        Some(json!({"checklistItemSubmitMode": "space"})),
        StatusCode::BAD_REQUEST,
    )
    .await;
    assert_eq!(
        invalid_checklist_mode["error"]["message"],
        json!("checklistItemSubmitMode has unsupported value")
    );

    let invalid_card_details_mode = request(
        &app,
        "PUT",
        "/api/v1/me/appearance",
        owner,
        Some(json!({"cardDetailsMode": "page"})),
        StatusCode::BAD_REQUEST,
    )
    .await;
    assert_eq!(
        invalid_card_details_mode["error"]["message"],
        json!("cardDetailsMode has unsupported value")
    );

    let invalid_density = request(
        &app,
        "PUT",
        &format!("/api/v1/boards/{board_id}/appearance"),
        owner,
        Some(json!({"columnDensity": "ultra"})),
        StatusCode::BAD_REQUEST,
    )
    .await;
    assert_eq!(
        invalid_density["error"]["message"],
        json!("columnDensity has unsupported value")
    );

    let missing_wallpaper_value = request(
        &app,
        "PUT",
        &format!("/api/v1/boards/{board_id}/appearance"),
        owner,
        Some(json!({"wallpaper": {"kind": "gradient"}})),
        StatusCode::BAD_REQUEST,
    )
    .await;
    assert_eq!(
        missing_wallpaper_value["error"]["message"],
        json!("wallpaper.value is required for non-none wallpapers")
    );

    let invalid_custom_properties = request(
        &app,
        "PUT",
        &format!("/api/v1/boards/{board_id}/appearance"),
        owner,
        Some(json!({"customProperties": ["not", "an", "object"]})),
        StatusCode::BAD_REQUEST,
    )
    .await;
    assert_eq!(
        invalid_custom_properties["error"]["message"],
        json!("customProperties must be a JSON object")
    );

    let invalid_accent_color = request(
        &app,
        "PUT",
        &format!("/api/v1/boards/{board_id}/appearance"),
        owner,
        Some(json!({"customProperties": {"accentColor": "violet"}})),
        StatusCode::BAD_REQUEST,
    )
    .await;
    assert_eq!(
        invalid_accent_color["error"]["message"],
        json!("customProperties.accentColor must be a #RRGGBB color")
    );

    Ok(())
}
