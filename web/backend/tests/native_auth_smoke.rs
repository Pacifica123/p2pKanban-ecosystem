use axum::{
    body::{to_bytes, Body},
    http::{header::SET_COOKIE, Request, StatusCode},
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
            name: "p2p-planner-native-auth-test".to_string(),
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
            body_limit_mb: 4,
            cors_allowed_origins: vec!["http://127.0.0.1:3000".to_string()],
        },
        auth: AuthSettings {
            jwt_secret: "native-auth-test-secret".to_string(),
            previous_jwt_secrets: vec![],
            access_token_ttl_minutes: 15,
            refresh_token_ttl_days: 30,
            public_signup_enabled: true,
            refresh_cookie_name: "p2p_kanban_refresh".to_string(),
            device_cookie_name: "p2p_kanban_device".to_string(),
            cookie_same_site: p2p_planner_backend::config::CookieSameSite::Lax,
            cookie_secure: false,
            enable_dev_header_auth: false,
            auth_rate_limit_window_secs: 60,
            auth_rate_limit_max_attempts: 50,
            sensitive_rate_limit_window_secs: 60,
            sensitive_rate_limit_max_attempts: 50,
        },
        transports: TransportSettings::default(),
    }
}

async fn setup() -> anyhow::Result<(PgPool, axum::Router)> {
    dotenvy::dotenv().ok();
    let database_url = std::env::var("TEST_DATABASE_URL")
        .or_else(|_| std::env::var("DATABASE_URL"))
        .or_else(|_| Settings::load().map(|settings| settings.database.url))
        .expect("TEST_DATABASE_URL, DATABASE_URL, or DATABASE__URL via Settings::load must be set");
    let pool = PgPool::connect(&database_url).await?;
    MIGRATOR.run(&pool).await?;
    let app = build_app(AppState::new(test_settings(database_url), pool.clone()));
    Ok((pool, app))
}

async fn request_json(
    app: &axum::Router,
    path: &str,
    body: Value,
    bearer: Option<&str>,
    expected_status: StatusCode,
) -> Value {
    let mut request = Request::builder()
        .method("POST")
        .uri(path)
        .header("content-type", "application/json")
        .header("x-p2pkanban-client", "android-native");
    if let Some(token) = bearer {
        request = request.header("authorization", format!("Bearer {token}"));
    }

    let response = app
        .clone()
        .oneshot(request.body(Body::from(body.to_string())).unwrap())
        .await
        .unwrap();
    let status = response.status();
    assert!(
        response.headers().get(SET_COOKIE).is_none(),
        "native auth must not depend on cookies"
    );
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap_or_else(|_| json!({}));
    assert_eq!(status, expected_status, "status={status}, body={value}");
    value
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL or DATABASE_URL pointing to PostgreSQL"]
async fn android_native_auth_flow() -> anyhow::Result<()> {
    let (_pool, app) = setup().await?;
    let email = format!("android-{}@example.com", Uuid::now_v7());
    let password = "correct-horse-battery-staple";

    let signed_up = request_json(
        &app,
        "/api/v1/auth/native/sign-up",
        json!({
            "email": email,
            "password": password,
            "displayName": "Android test",
        }),
        None,
        StatusCode::CREATED,
    )
    .await;
    let first = &signed_up["data"];
    assert_eq!(first["authenticated"], json!(true));
    assert_eq!(first["mode"], json!("native_refresh_token_plus_bearer"));
    assert!(first["accessToken"]
        .as_str()
        .is_some_and(|value| !value.is_empty()));
    assert!(first["refreshToken"]
        .as_str()
        .is_some_and(|value| !value.is_empty()));

    let refreshed = request_json(
        &app,
        "/api/v1/auth/native/refresh",
        json!({"refreshToken": first["refreshToken"]}),
        None,
        StatusCode::OK,
    )
    .await;
    let second = &refreshed["data"];
    assert_ne!(second["refreshToken"], first["refreshToken"]);

    let signed_out = request_json(
        &app,
        "/api/v1/auth/native/sign-out",
        json!({"refreshToken": second["refreshToken"]}),
        Some(second["accessToken"].as_str().unwrap()),
        StatusCode::OK,
    )
    .await;
    assert_eq!(signed_out["data"]["signedOut"], json!(true));

    let signed_in = request_json(
        &app,
        "/api/v1/auth/native/sign-in",
        json!({"email": email, "password": password}),
        None,
        StatusCode::OK,
    )
    .await;
    assert_eq!(signed_in["data"]["user"]["email"], json!(email));
    Ok(())
}
