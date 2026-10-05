use serde::Serialize;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MeResponse {
    pub id: String,
    pub email: String,
    pub display_name: String,
}

#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeviceResponse {
    pub id: String,
    pub display_name: String,
    pub platform: String,
}
