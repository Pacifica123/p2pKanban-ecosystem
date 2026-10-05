use argon2::{
    password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString},
    Argon2,
};
use axum::http::HeaderMap;
use rand::rngs::OsRng;
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    http::middleware::{cookie_value, origin},
    state::AppState,
};

use super::{
    dto::{
        AuthSuccessResponse, DevBootstrapUserRequest, DevBootstrapUserResponse,
        NativeAuthSuccessResponse, NativeRefreshRequest, NativeSignOutRequest, SessionResponse,
        SessionUserResponse, SignInRequest, SignOutResponse, SignUpRequest,
    },
    repo::{self, AuthUserRecord, DeviceRecord, SessionLookupRecord, SessionRecord},
    token::{
        access_token_expiry_epoch, generate_refresh_token, hash_opaque_token, sign_access_token,
        verify_access_token, AccessTokenClaims,
    },
};

const DEVICE_COOKIE_MAX_AGE_SECONDS: i64 = 60 * 60 * 24 * 365;

pub struct AuthSuccessEnvelope {
    pub payload: AuthSuccessResponse,
    pub refresh_token: String,
    pub refresh_cookie: String,
    pub device_cookie: String,
}

impl AuthSuccessEnvelope {
    pub fn into_native_payload(self) -> NativeAuthSuccessResponse {
        let AuthSuccessEnvelope {
            payload,
            refresh_token,
            ..
        } = self;

        NativeAuthSuccessResponse {
            authenticated: payload.authenticated,
            mode: "native_refresh_token_plus_bearer",
            access_token: payload.access_token,
            access_token_expires_at: payload.access_token_expires_at,
            refresh_token,
            session_id: payload.session_id,
            device_id: payload.device_id,
            user: payload.user,
        }
    }
}

pub struct SignOutEnvelope {
    pub payload: SignOutResponse,
    pub refresh_cookie: String,
}

fn ensure_dev_bootstrap_allowed(state: &AppState) -> AppResult<()> {
    match state
        .settings
        .app
        .env
        .trim()
        .to_ascii_lowercase()
        .replace('-', "_")
        .as_str()
    {
        "local" | "dev" | "development" | "test" | "testing" => Ok(()),
        _ => Err(AppError::not_found("Not found")),
    }
}

pub(super) fn normalize_email(value: &str) -> AppResult<String> {
    let normalized = value.trim().to_ascii_lowercase();
    if normalized.is_empty() || !normalized.contains('@') {
        return Err(AppError::bad_request(
            "email must look like an email address",
        ));
    }
    Ok(normalized)
}

fn normalize_display_name(value: &str) -> AppResult<String> {
    let display_name = value.trim();
    if display_name.len() < 2 {
        return Err(AppError::bad_request(
            "displayName must be at least 2 characters",
        ));
    }
    Ok(display_name.to_string())
}

pub(super) fn validate_password(value: &str) -> AppResult<()> {
    if value.len() < 8 {
        return Err(AppError::bad_request(
            "password must be at least 8 characters",
        ));
    }
    Ok(())
}

pub(super) fn hash_password(password: &str) -> AppResult<String> {
    let salt = SaltString::generate(&mut OsRng);
    Argon2::default()
        .hash_password(password.as_bytes(), &salt)
        .map(|hash| hash.to_string())
        .map_err(|_| AppError::internal())
}

fn verify_password(password: &str, password_hash: &str) -> AppResult<bool> {
    let parsed = PasswordHash::new(password_hash).map_err(|_| AppError::internal())?;
    Ok(Argon2::default()
        .verify_password(password.as_bytes(), &parsed)
        .is_ok())
}

fn is_android_native(headers: &HeaderMap) -> bool {
    headers
        .get("x-p2pkanban-client")
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| value.eq_ignore_ascii_case("android-native"))
}

fn infer_platform(headers: &HeaderMap, user_agent: Option<&str>) -> &'static str {
    if is_android_native(headers) {
        return "android";
    }

    let ua = user_agent.unwrap_or_default().to_ascii_lowercase();
    if ua.contains("android") {
        "android_web"
    } else if ua.contains("iphone") || ua.contains("ipad") || ua.contains("ios") {
        "ios_web"
    } else if ua.contains("windows") {
        "windows_web"
    } else if ua.contains("mac os") || ua.contains("macintosh") {
        "mac_web"
    } else if ua.contains("linux") {
        "linux_web"
    } else {
        "web"
    }
}

fn infer_device_display_name(headers: &HeaderMap, user_agent: Option<&str>) -> String {
    if is_android_native(headers) {
        return "p2pKanban Android".to_string();
    }

    let ua = user_agent.unwrap_or_default().to_ascii_lowercase();
    if ua.contains("firefox") {
        "Firefox browser".to_string()
    } else if ua.contains("edg/") {
        "Edge browser".to_string()
    } else if ua.contains("chrome") {
        "Chrome browser".to_string()
    } else if ua.contains("safari") {
        "Safari browser".to_string()
    } else {
        "Web browser".to_string()
    }
}

fn client_ip(headers: &HeaderMap) -> Option<String> {
    headers
        .get("x-forwarded-for")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split(',').next())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .or_else(|| {
            headers
                .get("x-real-ip")
                .and_then(|value| value.to_str().ok())
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
        })
}

fn user_agent(headers: &HeaderMap) -> Option<String> {
    headers
        .get(axum::http::header::USER_AGENT)
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn ensure_cookie_request_origin_allowed(state: &AppState, headers: &HeaderMap) -> AppResult<()> {
    let Some(request_origin) = origin(headers) else {
        return Ok(());
    };

    let allowed = state
        .settings
        .http
        .cors_allowed_origins
        .iter()
        .any(|candidate| candidate.trim_end_matches('/') == request_origin.trim_end_matches('/'));

    if allowed {
        Ok(())
    } else {
        Err(AppError::forbidden(
            "Origin is not allowed for cookie-bound auth action",
        ))
    }
}

fn set_cookie(
    name: &str,
    value: &str,
    max_age_seconds: i64,
    http_only: bool,
    state: &AppState,
) -> String {
    let mut parts = vec![
        format!("{name}={value}"),
        "Path=/".to_string(),
        format!("Max-Age={max_age_seconds}"),
        format!(
            "SameSite={}",
            state.settings.auth.cookie_same_site.as_set_cookie_value()
        ),
    ];

    if http_only {
        parts.push("HttpOnly".to_string());
    }
    if state.settings.auth.cookie_secure {
        parts.push("Secure".to_string());
    }

    parts.join("; ")
}

fn clear_cookie(name: &str, state: &AppState) -> String {
    let mut parts = vec![
        format!("{name}="),
        "Path=/".to_string(),
        "Max-Age=0".to_string(),
        format!(
            "SameSite={}",
            state.settings.auth.cookie_same_site.as_set_cookie_value()
        ),
        "HttpOnly".to_string(),
    ];

    if state.settings.auth.cookie_secure {
        parts.push("Secure".to_string());
    }

    parts.join("; ")
}

fn build_auth_success_payload(
    state: &AppState,
    user: &AuthUserRecord,
    session: &SessionRecord,
) -> AppResult<AuthSuccessResponse> {
    let exp = access_token_expiry_epoch(state.settings.auth.access_token_ttl_minutes)?;
    let access_token = sign_access_token(
        &state.settings.auth.jwt_secret,
        &AccessTokenClaims {
            sub: user.id.to_string(),
            sid: session.id.to_string(),
            did: Some(session.device_id.to_string()),
            exp,
        },
    )?;

    Ok(AuthSuccessResponse {
        authenticated: true,
        mode: "session_cookie_plus_bearer",
        access_token,
        access_token_expires_at: exp.to_string(),
        session_id: session.id.to_string(),
        device_id: session.device_id.to_string(),
        user: SessionUserResponse {
            id: user.id.to_string(),
            email: user.email.clone(),
            display_name: user.display_name.clone(),
        },
    })
}

async fn complete_session_auth(
    state: &AppState,
    user: &AuthUserRecord,
    device: &DeviceRecord,
    session: &SessionRecord,
    refresh_token: String,
) -> AppResult<AuthSuccessEnvelope> {
    let payload = build_auth_success_payload(state, user, session)?;
    let refresh_cookie = set_cookie(
        &state.settings.auth.refresh_cookie_name,
        &refresh_token,
        state.settings.auth.refresh_token_ttl_days * 24 * 60 * 60,
        true,
        state,
    );
    let device_cookie = set_cookie(
        &state.settings.auth.device_cookie_name,
        &device.id.to_string(),
        DEVICE_COOKIE_MAX_AGE_SECONDS,
        true,
        state,
    );

    Ok(AuthSuccessEnvelope {
        payload,
        refresh_token,
        refresh_cookie,
        device_cookie,
    })
}

pub(super) async fn create_authenticated_session(
    state: &AppState,
    user: &AuthUserRecord,
    headers: &HeaderMap,
) -> AppResult<AuthSuccessEnvelope> {
    let agent = user_agent(headers);
    let ip = client_ip(headers);
    let cookie_device_id = cookie_value(headers, &state.settings.auth.device_cookie_name)
        .as_deref()
        .and_then(|value| Uuid::parse_str(value).ok());

    let device = repo::resolve_or_create_device(
        &state.db,
        cookie_device_id,
        user.id,
        &infer_device_display_name(headers, agent.as_deref()),
        infer_platform(headers, agent.as_deref()),
    )
    .await?;

    let refresh_token = generate_refresh_token();
    let refresh_hash = hash_opaque_token(&refresh_token);
    let session = repo::create_session(
        &state.db,
        user,
        &device,
        &refresh_hash,
        agent.as_deref(),
        ip.as_deref(),
        state.settings.auth.refresh_token_ttl_days,
    )
    .await?;

    complete_session_auth(state, user, &device, &session, refresh_token).await
}

pub async fn sign_up(
    state: &AppState,
    headers: &HeaderMap,
    payload: SignUpRequest,
) -> AppResult<AuthSuccessEnvelope> {
    if !state.settings.auth.public_signup_enabled {
        return Err(AppError::forbidden("Public sign-up is disabled"));
    }

    let email = normalize_email(&payload.email)?;
    let display_name = normalize_display_name(&payload.display_name)?;
    validate_password(&payload.password)?;

    if repo::find_active_user_by_email(&state.db, &email)
        .await?
        .is_some()
    {
        return Err(AppError::conflict(
            "An active account already uses this email",
        ));
    }

    let password_hash = hash_password(&payload.password)?;
    let user = repo::create_user(
        &state.db,
        Uuid::now_v7(),
        &email,
        &display_name,
        &password_hash,
    )
    .await?;
    create_authenticated_session(state, &user, headers).await
}

pub async fn sign_in(
    state: &AppState,
    headers: &HeaderMap,
    payload: SignInRequest,
) -> AppResult<AuthSuccessEnvelope> {
    let user = authenticate_user_with_password(state, &payload.email, &payload.password).await?;
    create_authenticated_session(state, &user, headers).await
}

pub(super) async fn authenticate_user_with_password(
    state: &AppState,
    email: &str,
    password: &str,
) -> AppResult<AuthUserRecord> {
    let email = normalize_email(email)?;
    validate_password(password)?;

    let Some(user) = repo::find_active_user_by_email(&state.db, &email).await? else {
        return Err(AppError::unauthorized("Invalid email or password"));
    };

    let Some(password_hash) = user.password_hash.as_deref() else {
        return Err(AppError::unauthorized(
            "Password sign-in is not available for this account",
        ));
    };

    if !verify_password(password, password_hash)? {
        return Err(AppError::unauthorized("Invalid email or password"));
    }

    Ok(user)
}

async fn resolve_refresh_session(
    state: &AppState,
    refresh_token: &str,
) -> AppResult<SessionLookupRecord> {
    let refresh_hash = hash_opaque_token(refresh_token);
    let Some(session) = repo::find_session_by_refresh_hash(&state.db, &refresh_hash).await? else {
        return Err(AppError::unauthorized(
            "Refresh session is missing or expired",
        ));
    };

    if session.revoked {
        let _ = repo::revoke_all_sessions_for_user(&state.db, session.user_id).await?;
        return Err(AppError::unauthorized(
            "Refresh token reuse detected; all sessions revoked",
        ));
    }

    Ok(session)
}

async fn rotate_refresh_session(
    state: &AppState,
    headers: &HeaderMap,
    refresh_token: String,
) -> AppResult<AuthSuccessEnvelope> {
    let session_lookup = resolve_refresh_session(state, &refresh_token).await?;

    let Some(device_id) = session_lookup.device_id else {
        return Err(AppError::unauthorized(
            "Refresh session is missing device binding",
        ));
    };

    let Some(user) = repo::find_active_user_by_id(&state.db, session_lookup.user_id).await? else {
        return Err(AppError::unauthorized(
            "Refresh session user no longer exists",
        ));
    };

    let new_refresh_token = generate_refresh_token();
    let new_refresh_hash = hash_opaque_token(&new_refresh_token);
    let agent = user_agent(headers);
    let ip = client_ip(headers);

    repo::rotate_session_refresh(
        &state.db,
        session_lookup.session_id,
        &new_refresh_hash,
        agent.as_deref(),
        ip.as_deref(),
        state.settings.auth.refresh_token_ttl_days,
    )
    .await?;

    let session = SessionRecord {
        id: session_lookup.session_id,
        user_id: user.id,
        device_id,
        email: session_lookup.email,
        display_name: session_lookup.display_name,
    };
    let device = DeviceRecord {
        id: device_id,
        display_name: infer_device_display_name(headers, agent.as_deref()),
        platform: infer_platform(headers, agent.as_deref()).to_string(),
    };

    complete_session_auth(state, &user, &device, &session, new_refresh_token).await
}

pub async fn refresh(state: &AppState, headers: &HeaderMap) -> AppResult<AuthSuccessEnvelope> {
    ensure_cookie_request_origin_allowed(state, headers)?;

    let refresh_token = cookie_value(headers, &state.settings.auth.refresh_cookie_name)
        .ok_or_else(|| AppError::unauthorized("Refresh cookie is missing"))?;
    rotate_refresh_session(state, headers, refresh_token).await
}

pub async fn native_refresh(
    state: &AppState,
    headers: &HeaderMap,
    payload: NativeRefreshRequest,
) -> AppResult<AuthSuccessEnvelope> {
    let refresh_token = payload.refresh_token.trim().to_string();
    if refresh_token.is_empty() {
        return Err(AppError::unauthorized("Refresh token is missing"));
    }
    rotate_refresh_session(state, headers, refresh_token).await
}

pub async fn sign_out(state: &AppState, headers: &HeaderMap) -> AppResult<SignOutEnvelope> {
    ensure_cookie_request_origin_allowed(state, headers)?;

    if let Some(refresh_token) = cookie_value(headers, &state.settings.auth.refresh_cookie_name) {
        if let Ok(session) = resolve_refresh_session(state, &refresh_token).await {
            let _ = repo::revoke_session(&state.db, session.session_id).await;
        }
    }

    Ok(SignOutEnvelope {
        payload: SignOutResponse {
            signed_out: true,
            mode: "session_cookie_plus_bearer",
        },
        refresh_cookie: clear_cookie(&state.settings.auth.refresh_cookie_name, state),
    })
}

pub async fn native_sign_out(
    state: &AppState,
    payload: NativeSignOutRequest,
) -> AppResult<SignOutResponse> {
    let refresh_token = payload.refresh_token.trim();
    if !refresh_token.is_empty() {
        if let Ok(session) = resolve_refresh_session(state, refresh_token).await {
            let _ = repo::revoke_session(&state.db, session.session_id).await;
        }
    }

    Ok(SignOutResponse {
        signed_out: true,
        mode: "native_refresh_token_plus_bearer",
    })
}

pub async fn sign_out_all(
    state: &AppState,
    headers: &HeaderMap,
    current_user_id: Uuid,
) -> AppResult<SignOutEnvelope> {
    ensure_cookie_request_origin_allowed(state, headers)?;
    let _ = repo::revoke_all_sessions_for_user(&state.db, current_user_id).await?;

    Ok(SignOutEnvelope {
        payload: SignOutResponse {
            signed_out: true,
            mode: "session_cookie_plus_bearer",
        },
        refresh_cookie: clear_cookie(&state.settings.auth.refresh_cookie_name, state),
    })
}

pub async fn get_session(state: &AppState, headers: &HeaderMap) -> AppResult<SessionResponse> {
    if let Some(access_token) = crate::http::middleware::bearer_token(headers) {
        if let Ok(claims) = verify_access_token(
            &access_token,
            &state.settings.auth.jwt_secret,
            &state.settings.auth.previous_jwt_secrets,
        ) {
            let user_id = claims.user_id()?;
            let session_id = claims.session_id()?;
            if let Some(session) =
                repo::find_session_principal(&state.db, user_id, session_id).await?
            {
                return Ok(SessionResponse {
                    authenticated: true,
                    mode: "session_cookie_plus_bearer",
                    session_id: Some(session.id.to_string()),
                    device_id: Some(session.device_id.to_string()),
                    user: Some(SessionUserResponse {
                        id: session.user_id.to_string(),
                        email: session.email,
                        display_name: session.display_name,
                    }),
                });
            }
        }
    }

    if let Some(refresh_token) = cookie_value(headers, &state.settings.auth.refresh_cookie_name) {
        if let Ok(session_lookup) = resolve_refresh_session(state, &refresh_token).await {
            return Ok(SessionResponse {
                authenticated: true,
                mode: "session_cookie_only",
                session_id: Some(session_lookup.session_id.to_string()),
                device_id: session_lookup.device_id.map(|value| value.to_string()),
                user: Some(SessionUserResponse {
                    id: session_lookup.user_id.to_string(),
                    email: session_lookup.email,
                    display_name: session_lookup.display_name,
                }),
            });
        }
    }

    Ok(SessionResponse {
        authenticated: false,
        mode: "anonymous",
        session_id: None,
        device_id: None,
        user: None,
    })
}

pub async fn bootstrap_dev_user(
    state: &AppState,
    payload: DevBootstrapUserRequest,
) -> AppResult<DevBootstrapUserResponse> {
    ensure_dev_bootstrap_allowed(state)?;

    let user_id = match payload.user_id.as_deref() {
        Some(value) => Uuid::parse_str(value)
            .map_err(|_| AppError::bad_request("userId must be a valid UUID"))?,
        None => Uuid::now_v7(),
    };

    let email = payload
        .email
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| format!("smoke-{}@local.test", user_id));

    let display_name = payload
        .display_name
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "Smoke Test User".to_string());

    if !email.contains('@') {
        return Err(AppError::bad_request(
            "email must look like an email address",
        ));
    }

    repo::bootstrap_dev_user(&state.db, user_id, &email, &display_name).await
}
