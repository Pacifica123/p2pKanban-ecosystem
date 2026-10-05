//! Insert-only admission of unknown boards through a previously trusted owner.
use std::collections::HashSet;
use serde_json::{json, Value};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
use crate::{error::{AppError, AppResult}, modules::integrations::dto::{PortableBundle, PortableBundlePayload}};
use super::{dto::NodeLinkExportResponse, pairing};
type Verified = (Uuid, Uuid, String, i64, Vec<Value>);
fn ids(rows: &Value) -> HashSet<String> {
    rows.as_array().into_iter().flatten().filter_map(|v| v["id"].as_str().map(str::to_owned)).collect()
}
fn retain(rows: &mut Value, key: &str, selected: &HashSet<String>) {
    if let Some(rows) = rows.as_array_mut() { rows.retain(|v| v[key].as_str().is_some_and(|id| selected.contains(id))); }
}
fn select_boards(bundle: &PortableBundle, selected: &HashSet<String>, deleted: &HashSet<String>, include_workspace: bool) -> PortableBundle {
    let mut result = bundle.clone();
    select_payload(&mut result.payload, selected, deleted);
    if include_workspace { result.payload.workspaces=bundle.payload.workspaces.clone(); }
    result
}
fn select_payload(p: &mut PortableBundlePayload, selected: &HashSet<String>, deleted: &HashSet<String>) {
    p.workspaces = json!([]);
    retain(&mut p.boards, "id", selected);
    retain(&mut p.columns, "boardId", selected);
    retain(&mut p.cards, "boardId", selected);
    if let Some(rows) = p.cards.as_array_mut() {
        rows.retain(|v| !v["id"].as_str().is_some_and(|id| deleted.contains(id)));
        for card in rows {
            if card["parentCardId"].as_str().is_some_and(|id| deleted.contains(id)) { card["parentCardId"] = Value::Null; }
        }
    }
    let cards = ids(&p.cards);
    retain(&mut p.labels, "boardId", selected);
    let labels = ids(&p.labels);
    retain(&mut p.card_labels, "boardId", selected);
    retain(&mut p.card_labels, "cardId", &cards);
    retain(&mut p.card_labels, "labelId", &labels);
    retain(&mut p.checklists, "cardId", &cards);
    let lists = ids(&p.checklists);
    retain(&mut p.checklist_items, "checklistId", &lists);
    retain(&mut p.comments, "cardId", &cards);
    retain(&mut p.board_appearance_settings, "boardId", selected);
    p.activity_entries = json!([]);
}
pub(super) async fn import_missing(tx: &mut Transaction<'_, Postgres>, remote: &NodeLinkExportResponse, verified: &[Verified]) -> AppResult<usize> {
    let mut selected = HashSet::new();
    let mut new_workspaces=HashSet::new();
    for (board, workspace, root, epoch, _) in verified {
        let exists = sqlx::query_scalar::<_, bool>("select exists(select 1 from boards where id=$1) or exists(select 1 from tombstones where entity_type='board' and entity_id=$1)")
            .bind(board).fetch_one(&mut **tx).await?;
        if exists { continue; }
        let trusted=sqlx::query_scalar::<_,bool>(r#"
          select exists(select 1 from trusted_device_peers where user_id=$1 and public_key=$2)
          or exists(select 1 from roaming_device_grants g join boards b on b.id=g.board_id
             join workspaces w on w.id=b.workspace_id where g.user_id=$1 and g.root_key=$2
             and g.epoch=w.access_epoch and w.owner_user_id=$1 and w.deleted_at is null)
        "#).bind(remote.user.id).bind(root).fetch_one(&mut **tx).await?;
        if !trusted { return Err(AppError::forbidden("Ключ отправителя не принадлежит ранее доверенному устройству")); }
        let current=sqlx::query_scalar::<_,i64>("select access_epoch from workspaces where id=$1 and owner_user_id=$2 and deleted_at is null")
          .bind(workspace).bind(remote.user.id).fetch_optional(&mut **tx).await?;
        if let Some(value)=current {if value!=*epoch{return Err(AppError::conflict("Epoch пространства изменился; нужна повторная выдача ключей"));}}
        else {
          let collision=sqlx::query_scalar::<_,bool>("select exists(select 1 from workspaces where id=$1)")
            .bind(workspace).fetch_one(&mut **tx).await?;
          if collision{return Err(AppError::conflict("Идентификатор пространства занят другим владельцем"));}
          new_workspaces.insert(workspace.to_string());
        }
        selected.insert(board.to_string());
    }
    let local_deleted = sqlx::query_scalar::<_, Uuid>("select entity_id from tombstones where entity_type='card'").fetch_all(&mut **tx).await?;
    let local_deleted: HashSet<String> = local_deleted.into_iter().map(|id| id.to_string()).collect();
    let deleted: HashSet<String> = local_deleted.iter().cloned().chain(remote.card_tombstones.iter().map(|t| t.card_id.to_string())).collect();
    for t in &remote.card_tombstones {
        if !selected.contains(&t.board_id.to_string()) { continue; }
        let collision = sqlx::query_scalar::<_, bool>("select exists(select 1 from cards where id=$1 and board_id<>$2)")
            .bind(t.card_id).bind(t.board_id).fetch_one(&mut **tx).await?;
        if collision { return Err(AppError::conflict("Tombstone ссылается на существующую карточку другой доски")); }
    }
    for workspace in &remote.workspaces {
        let workspace_id=workspace.bundle.manifest_json.workspace_id.ok_or_else(||AppError::bad_request("No workspace ID"))?;
        let include_workspace=new_workspaces.contains(&workspace_id.to_string());
        let bundle=select_boards(&workspace.bundle,&selected,&deleted,include_workspace);
        if bundle.payload.boards.as_array().is_some_and(|v|!v.is_empty()) {
          pairing::import_workspace_bundle_parts(tx,remote.user.id,&bundle,include_workspace).await?;
          if include_workspace {
            let epoch=verified.iter().find(|(_,id,_,_,_)|*id==workspace_id).map(|(_,_,_,epoch,_)|*epoch).unwrap_or(1);
            sqlx::query("update workspaces set access_epoch=$2 where id=$1")
              .bind(workspace_id).bind(epoch).execute(&mut **tx).await?;
          }
        }
    }
    let capabilities = remote.board_capabilities.iter().filter(|c| selected.contains(&c.board_id.to_string())).cloned().collect::<Vec<_>>();
    pairing::import_board_capabilities(tx, &capabilities).await?;
    for (board, workspace, root, epoch, chain) in verified {
        if !selected.contains(&board.to_string()) { continue; }
        sqlx::query("update roaming_board_capabilities set capability_epoch=$2 where board_id=$1").bind(board).bind(epoch).execute(&mut **tx).await?;
        sqlx::query("insert into roaming_device_grants(board_id,user_id,root_key,chain_json,epoch) values($1,$2,$3,$4,$5)")
            .bind(board).bind(remote.user.id).bind(root).bind(json!(chain)).bind(epoch).execute(&mut **tx).await?;
        sqlx::query("insert into roaming_board_authorizations(id,workspace_id,board_id,user_id,author_public_key,role,capability_epoch) values($1,$2,$3,$4,$5,'owner',$6)")
            .bind(Uuid::now_v7()).bind(workspace).bind(board).bind(remote.user.id).bind(root).bind(epoch).execute(&mut **tx).await?;
    }
    let tombstones = remote.card_tombstones.iter().filter(|t| selected.contains(&t.board_id.to_string()) && !local_deleted.contains(&t.card_id.to_string())).cloned().collect::<Vec<_>>();
    pairing::import_card_tombstones(tx, &tombstones).await?;
    Ok(selected.len())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn additive_selection_preserves_existing_boards_and_tombstones() {
        let mut p = PortableBundlePayload {
            workspaces: json!([{"id":"workspace"}]), boards: json!([{"id":"old"},{"id":"new"}]),
            columns: json!([{"id":"oc","boardId":"old"},{"id":"nc","boardId":"new"}]),
            cards: json!([{"id":"old-card","boardId":"old"},{"id":"dead","boardId":"new"},{"id":"live","boardId":"new","parentCardId":"dead"}]),
            labels: json!([{"id":"label","boardId":"new"}]), card_labels: json!([{"boardId":"new","cardId":"dead","labelId":"label"}]),
            checklists: json!([{"id":"dead-list","cardId":"dead"},{"id":"live-list","cardId":"live"}]),
            checklist_items: json!([{"checklistId":"dead-list"},{"checklistId":"live-list"}]),
            comments: json!([{"cardId":"dead"},{"cardId":"live"}]),
            board_appearance_settings: json!([{"boardId":"old"},{"boardId":"new"}]), activity_entries: json!([{"id":"irrelevant"}]),
        };
        select_payload(&mut p, &HashSet::from(["new".into()]), &HashSet::from(["dead".into()]));
        assert_eq!(p.workspaces,json!([])); assert_eq!(p.boards,json!([{"id":"new"}]));
        assert_eq!(p.cards,json!([{"id":"live","boardId":"new","parentCardId":null}]));
        assert_eq!(p.checklist_items,json!([{"checklistId":"live-list"}])); assert_eq!(p.comments,json!([{"cardId":"live"}]));
        assert_eq!(p.card_labels,json!([])); assert_eq!(p.activity_entries,json!([]));
        select_payload(&mut p, &HashSet::new(), &HashSet::new());
        assert_eq!(p.cards,json!([])); assert_eq!(p.boards,json!([])); assert_eq!(p.checklist_items,json!([]));
    }
}
