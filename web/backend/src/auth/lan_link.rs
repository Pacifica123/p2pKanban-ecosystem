//! LAN invitation delivery; board updates still flow through autonomous replicas.
use super::{device_link::{check_request,create_request,prepared,secret},pairing};
use crate::{error::{AppError,AppResult},http::response::{ok,ApiEnvelope},modules::common::auth_context,state::AppState};
use axum::{extract::{Path,State},http::HeaderMap,Json};
use p2p_kanban_nostr_transport::device_link as protocol;
use serde::Deserialize;
use serde_json::{json,Value};
use std::{net::IpAddr,time::Duration};
fn invalid(e:impl std::fmt::Display)->AppError{AppError::bad_request(format!("Device link: {e}"))}
fn endpoint(input:&str,path:&str)->AppResult<reqwest::Url>{
 let address=if input.contains("://"){input.to_owned()}else{format!("http://{input}")};
 let mut url=reqwest::Url::parse(&address).map_err(invalid)?;
 if url.scheme()!="http"||!url.username().is_empty()||url.password().is_some()||url.query().is_some()
    ||url.fragment().is_some()||!matches!(url.path(),""|"/"){return Err(invalid("Укажите http://IP:port без пути"));}
 let ip:IpAddr=url.host_str().ok_or_else(||invalid("IP отсутствует"))?.parse().map_err(|_|invalid("Нужен числовой IP"))?;
 let private=match ip{IpAddr::V4(v)=>v.is_private()||v.is_loopback()||v.is_link_local(),
   IpAddr::V6(v)=>v.is_unique_local()||v.is_loopback()||v.is_unicast_link_local()};
 if !private||url.port().is_none(){return Err(invalid("Нужны IP и порт локальной сети"));}
 url.set_path(path);Ok(url)
}
fn client()->AppResult<reqwest::Client>{reqwest::Client::builder().no_proxy()
 .redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(12)).build().map_err(invalid)}
#[derive(Deserialize)]
#[serde(rename_all="camelCase")]
pub struct Connect{address:String,#[serde(default)]supplement:bool}
pub async fn connect(State(s):State<AppState>,h:HeaderMap,Json(input):Json<Connect>)->AppResult<Json<ApiEnvelope<Value>>>{
 let url=endpoint(&input.address,"/api/v1/auth/device-link/lan/inbox")?;
 if input.supplement{auth_context(&s,&h).await?;}else{pairing::ensure_empty_destination(&s).await?;}
 let signed=create_request(&s,input.supplement).await?.0.data;
 let id=signed["id"].as_str().ok_or_else(||invalid("invalid request"))?.to_owned();
 let response=client()?.post(url.clone()).json(&signed).send().await.map_err(invalid)?;
 if !response.status().is_success(){return Err(invalid(format!("Узел отклонил запрос: {}",response.status())));}
 sqlx::query("insert into device_link_lan_outbound(id,peer_url) values($1,$2) on conflict(id) do update set peer_url=excluded.peer_url")
  .bind(&id).bind(url.as_str()).execute(&s.db).await?;
 Ok(ok(json!({"request":signed,"peer":url.origin().ascii_serialization()})))
}
pub async fn receive(State(s):State<AppState>,Json(request):Json<Value>)->AppResult<Json<ApiEnvelope<Value>>>{
 let (_,id,expiry)=check_request(&request)?;
 sqlx::query("delete from device_link_lan_inbox where expires_at<$1").bind(protocol::now() as i64).execute(&s.db).await?;
 sqlx::query("insert into device_link_lan_inbox(id,request_json,expires_at) values($1,$2,$3) on conflict(id) do nothing")
  .bind(&id).bind(&request).bind(expiry as i64).execute(&s.db).await?;
 Ok(ok(json!({"requestId":id})))
}
pub async fn inbox(State(s):State<AppState>,h:HeaderMap)->AppResult<Json<ApiEnvelope<Value>>>{
 auth_context(&s,&h).await?;
 let rows=sqlx::query_scalar::<_,Value>("select request_json from device_link_lan_inbox where expires_at>$1 and approved_at is null order by expires_at desc limit 20")
  .bind(protocol::now() as i64).fetch_all(&s.db).await?;
 Ok(ok(json!(rows)))
}
#[derive(Deserialize)]
#[serde(rename_all="camelCase")]
pub struct Approve{request_id:String,confirmed_request_id:String}
pub async fn approve(State(s):State<AppState>,h:HeaderMap,Json(input):Json<Approve>)->AppResult<Json<ApiEnvelope<Value>>>{
 let auth=auth_context(&s,&h).await?;
 if input.request_id!=input.confirmed_request_id{return Err(invalid("Сверьте отпечаток"));}
 let request=sqlx::query_scalar::<_,Value>("select request_json from device_link_lan_inbox where id=$1 and expires_at>$2 and approved_at is null")
  .bind(&input.request_id).bind(protocol::now() as i64).fetch_optional(&s.db).await?.ok_or_else(||invalid("Запрос истёк или одобрен"))?;
 let (recipient,id,expiry)=check_request(&request)?;
 let data=prepared(&s,auth.user_id,&recipient).await?;
 let parts=protocol::encrypt(secret(&s)?,&recipient,&data).map_err(invalid)?;
 let response=protocol::sign(secret(&s)?,protocol::RESPONSE_KIND,&json!({"protocol":protocol::PROTOCOL,
   "recipient":recipient,"requestId":id,"expiresAt":expiry,"parts":parts})).map_err(invalid)?;
 let mut tx=s.db.begin().await?;
 let changed=sqlx::query("update device_link_lan_inbox set response_json=$2,approved_at=now() where id=$1 and expires_at>$3 and approved_at is null")
  .bind(&id).bind(&response).bind(protocol::now() as i64).execute(&mut *tx).await?;
 if changed.rows_affected()!=1{return Err(invalid("Запрос уже обработан"));}
 sqlx::query("insert into trusted_device_peers(user_id,public_key) values($1,$2) on conflict do nothing")
  .bind(auth.user_id).bind(&recipient).execute(&mut *tx).await?;
 tx.commit().await?;
 Ok(ok(json!({"approved":true})))
}
pub async fn result(State(s):State<AppState>,Path(id):Path<String>)->AppResult<Json<ApiEnvelope<Value>>>{
 if id.len()!=64||!id.bytes().all(|c|c.is_ascii_hexdigit()){return Err(invalid("Invalid request ID"));}
 let response=sqlx::query_scalar::<_,Option<Value>>("select response_json from device_link_lan_inbox where id=$1 and expires_at>$2")
  .bind(id).bind(protocol::now() as i64).fetch_optional(&s.db).await?.flatten();
 Ok(ok(json!({"response":response})))
}
pub async fn poll(State(s):State<AppState>,h:HeaderMap,Path(id):Path<String>)->AppResult<Json<ApiEnvelope<Value>>>{
 let row=sqlx::query_as::<_,(String,Value,bool)>("select o.peer_url,c.request_json,c.consumed_at is not null from device_link_lan_outbound o join device_link_challenges c on c.id=o.id where o.id=$1 and c.expires_at>$2")
  .bind(&id).bind(protocol::now() as i64).fetch_optional(&s.db).await?.ok_or_else(||invalid("Запрос истёк"))?;
 if row.2{return Err(invalid("Запрос использован"));}
 let body=protocol::checked_event(&row.1,protocol::REQUEST_KIND).map_err(invalid)?.2;
 if body["supplement"]==true{auth_context(&s,&h).await?;}
 let origin=reqwest::Url::parse(&row.0).map_err(invalid)?.origin().ascii_serialization();
 let url=endpoint(&origin,&format!("/api/v1/auth/device-link/lan/result/{id}"))?;
 let response=client()?.get(url).send().await.map_err(invalid)?;
 if !response.status().is_success(){return Err(invalid(format!("Узел недоступен: {}",response.status())));}
 let payload:Value=response.json().await.map_err(invalid)?;
 Ok(ok(json!({"response":payload["data"]["response"]})))
}
pub async fn mobile_result(State(s):State<AppState>,Json(response):Json<Value>)->AppResult<Json<ApiEnvelope<Value>>>{
 let (_,_,body)=protocol::checked_event(&response,protocol::RESPONSE_KIND).map_err(invalid)?;
 let id=body["requestId"].as_str().ok_or_else(||invalid("missing request ID"))?;
 let recipient=protocol::public_key(secret(&s)?).map_err(invalid)?;
 if body["protocol"]!=protocol::PROTOCOL||body["recipient"]!=recipient
  ||body["expiresAt"].as_u64().is_none_or(|e|e<=protocol::now())
 {return Err(invalid("Ответ адресован другому устройству или истёк"));}
 let row=sqlx::query_as::<_,(Value,bool)>("select request_json,consumed_at is not null from device_link_challenges where id=$1 and expires_at>$2")
  .bind(id).bind(protocol::now() as i64).fetch_optional(&s.db).await?.ok_or_else(||invalid("Нет ожидающего запроса"))?;
 let (requester,rid,expiry)=check_request(&row.0)?;
 if row.1||rid!=id||requester!=recipient||body["expiresAt"]!=expiry{return Err(invalid("Ответ не соответствует запросу"));}
 sqlx::query("update device_link_challenges set lan_mobile_response=$2 where id=$1 and consumed_at is null and expires_at>$3")
  .bind(id).bind(&response).bind(protocol::now() as i64).execute(&s.db).await?;
 Ok(ok(json!({"received":true})))
}
pub async fn mobile_poll(State(s):State<AppState>,h:HeaderMap,Path(id):Path<String>)->AppResult<Json<ApiEnvelope<Value>>>{
 let row=sqlx::query_as::<_,(Value,Option<Value>,bool)>("select request_json,lan_mobile_response,consumed_at is not null from device_link_challenges where id=$1 and expires_at>$2")
  .bind(&id).bind(protocol::now() as i64).fetch_optional(&s.db).await?.ok_or_else(||invalid("Запрос истёк"))?;
 if row.2{return Err(invalid("Запрос использован"));}
 let body=protocol::checked_event(&row.0,protocol::REQUEST_KIND).map_err(invalid)?.2;
 if body["supplement"]==true{auth_context(&s,&h).await?;}
 Ok(ok(json!({"response":row.1})))
}
pub async fn pending_request(State(s):State<AppState>)->AppResult<Json<ApiEnvelope<Value>>>{
 let row=sqlx::query_scalar::<_,Value>("select request_json from device_link_challenges where consumed_at is null and expires_at>$1 order by created_at desc limit 1")
  .bind(protocol::now() as i64).fetch_optional(&s.db).await?;
 Ok(ok(json!({"request":row})))
}

#[cfg(test)]
mod tests {
 use super::*;
 #[test]
 fn only_literal_private_addresses_and_root_paths() {
  assert!(endpoint("192.168.1.8:8080","/api/v1/auth/device-link/lan/inbox").is_ok());
  for input in ["http://example.org:8080","http://8.8.8.8:8080",
    "http://192.168.1.8:8080/redirect","http://user@192.168.1.8:8080",
    "http://192.168.1.8:8080?next=http://8.8.8.8",
    "https://192.168.1.8:8080"] {
    assert!(endpoint(input,"/api/v1/auth/device-link/lan/inbox").is_err(),"{input}");
  }
 }
}
