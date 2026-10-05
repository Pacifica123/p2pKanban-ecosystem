use axum::{
    extract::State,
    http::{header::SET_COOKIE, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};

use crate::{
    error::AppResult,
    http::response::{ok, ApiEnvelope},
    modules::common::actor_user_id,
    state::AppState,
};

use super::{
    dto::{
        DevBootstrapUserRequest, DevBootstrapUserResponse, NativeAuthSuccessResponse,
        NativeRefreshRequest, NativeSignOutRequest, NodeLinkExportRequest, NodeLinkExportResponse,
        NodeLinkImportRequest, SessionResponse, SignInRequest, SignOutResponse, SignUpRequest,
    },
    service,
};

pub(super) fn response_with_cookies<T: serde::Serialize>(
    status: StatusCode,
    data: T,
    cookies: &[String],
) -> AppResult<Response> {
    let mut response = (status, ok(data)).into_response();
    for cookie in cookies {
        let header_value =
            HeaderValue::from_str(cookie).map_err(|_| crate::error::AppError::internal())?;
        response.headers_mut().append(SET_COOKIE, header_value);
    }
    Ok(response)
}

pub async fn sign_up(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<SignUpRequest>,
) -> AppResult<Response> {
    let result = service::sign_up(&state, &headers, payload).await?;
    response_with_cookies(
        StatusCode::CREATED,
        result.payload,
        &[result.refresh_cookie, result.device_cookie],
    )
}

pub async fn sign_in(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<SignInRequest>,
) -> AppResult<Response> {
    let result = service::sign_in(&state, &headers, payload).await?;
    response_with_cookies(
        StatusCode::OK,
        result.payload,
        &[result.refresh_cookie, result.device_cookie],
    )
}

pub async fn export_node_link(
    State(state): State<AppState>,
    Json(payload): Json<NodeLinkExportRequest>,
) -> AppResult<Json<ApiEnvelope<NodeLinkExportResponse>>> {
    Ok(ok(super::pairing::export_node_link(&state, payload).await?))
}

pub async fn import_node_link(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<NodeLinkImportRequest>,
) -> AppResult<Response> {
    let result = super::pairing::import_node_link(&state, &headers, payload).await?;
    response_with_cookies(
        StatusCode::CREATED,
        result.payload,
        &[result.refresh_cookie, result.device_cookie],
    )
}

pub async fn refresh(State(state): State<AppState>, headers: HeaderMap) -> AppResult<Response> {
    let result = service::refresh(&state, &headers).await?;
    response_with_cookies(
        StatusCode::OK,
        result.payload,
        &[result.refresh_cookie, result.device_cookie],
    )
}

pub async fn sign_out(State(state): State<AppState>, headers: HeaderMap) -> AppResult<Response> {
    let result = service::sign_out(&state, &headers).await?;
    response_with_cookies(StatusCode::OK, result.payload, &[result.refresh_cookie])
}

pub async fn sign_out_all(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<Response> {
    let actor = actor_user_id(&state, &headers).await?;
    let result = service::sign_out_all(&state, &headers, actor).await?;
    response_with_cookies(StatusCode::OK, result.payload, &[result.refresh_cookie])
}

pub async fn native_sign_up(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<SignUpRequest>,
) -> AppResult<Response> {
    let result = service::sign_up(&state, &headers, payload).await?;
    Ok((
        StatusCode::CREATED,
        ok::<NativeAuthSuccessResponse>(result.into_native_payload()),
    )
        .into_response())
}

pub async fn native_sign_in(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<SignInRequest>,
) -> AppResult<Response> {
    let result = service::sign_in(&state, &headers, payload).await?;
    Ok((
        StatusCode::OK,
        ok::<NativeAuthSuccessResponse>(result.into_native_payload()),
    )
        .into_response())
}

pub async fn native_refresh(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<NativeRefreshRequest>,
) -> AppResult<Json<ApiEnvelope<NativeAuthSuccessResponse>>> {
    let result = service::native_refresh(&state, &headers, payload).await?;
    Ok(ok(result.into_native_payload()))
}

pub async fn native_sign_out(
    State(state): State<AppState>,
    Json(payload): Json<NativeSignOutRequest>,
) -> AppResult<Json<ApiEnvelope<SignOutResponse>>> {
    Ok(ok(service::native_sign_out(&state, payload).await?))
}

pub async fn bootstrap_dev_user(
    State(state): State<AppState>,
    Json(payload): Json<DevBootstrapUserRequest>,
) -> AppResult<Json<ApiEnvelope<DevBootstrapUserResponse>>> {
    let user = service::bootstrap_dev_user(&state, payload).await?;
    Ok(ok(user))
}

pub async fn get_session(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<Json<ApiEnvelope<SessionResponse>>> {
    Ok(ok(service::get_session(&state, &headers).await?))
}
