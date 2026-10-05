use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{params, Connection, ErrorCode, OptionalExtension, Transaction, TransactionBehavior};
use uuid::Uuid;

use crate::{
    application::parity::{ParityRepository, ParityRepositoryError},
    domain::{
        parity::{ActivityEntryId, ActivityEntryRecord, BoardAppearanceRecord, CardLabelRecord, CommentId, CommentRecord, LabelId, LabelRecord},
        planner::{BoardId, CardId, OrderKey, WorkspaceId},
    },
    infrastructure::profile::ProfileStoragePaths,
};

use super::migration::{open_profile, ProfileOpenError};

pub struct SqliteParityRepository {
    connection: Connection,
}

impl SqliteParityRepository {
    pub fn open(layout: &ProfileStoragePaths) -> Result<Self, ProfileOpenError> {
        let (connection, _) = open_profile(layout)?;
        Ok(Self { connection })
    }
}

fn storage<T>(_: T) -> ParityRepositoryError { ParityRepositoryError::StorageFailure }

fn constraint(error: rusqlite::Error, duplicate: ParityRepositoryError) -> ParityRepositoryError {
    match &error {
        rusqlite::Error::SqliteFailure(inner, _) if inner.code == ErrorCode::ConstraintViolation => duplicate,
        _ => ParityRepositoryError::StorageFailure,
    }
}

fn now_millis() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|value| value.as_millis().min(i64::MAX as u128) as i64).unwrap_or(0)
}

fn board_workspace_on(conn: &Connection, board_id: &BoardId) -> Result<WorkspaceId, ParityRepositoryError> {
    let workspace_id: Option<String> = conn.query_row(
        "SELECT workspace_id FROM boards WHERE id=?1", [board_id.as_str()], |row| row.get(0),
    ).optional().map_err(storage)?;
    let workspace_id = workspace_id.ok_or(ParityRepositoryError::BoardNotFound)?;
    WorkspaceId::new(workspace_id).map_err(storage)
}

fn card_scope_on(conn: &Connection, card_id: &CardId) -> Result<(WorkspaceId, BoardId), ParityRepositoryError> {
    let value: Option<(String, String)> = conn.query_row(
        "SELECT workspace_id, board_id FROM cards WHERE id=?1", [card_id.as_str()],
        |row| Ok((row.get(0)?, row.get(1)?)),
    ).optional().map_err(storage)?;
    let (workspace_id, board_id) = value.ok_or(ParityRepositoryError::CardNotFound)?;
    Ok((WorkspaceId::new(workspace_id).map_err(storage)?, BoardId::new(board_id).map_err(storage)?))
}

fn actor_user_id(tx: &Transaction<'_>) -> Result<Option<String>, ParityRepositoryError> {
    tx.query_row("SELECT user_id FROM profile_principal WHERE singleton=1", [], |row| row.get(0))
        .optional().map_err(storage)
}

fn insert_activity(tx: &Transaction<'_>, mut value: ActivityEntryRecord) -> Result<(), ParityRepositoryError> {
    if value.actor_user_id.is_none() { value.actor_user_id = actor_user_id(tx)?; }
    tx.execute(
        "INSERT INTO activity_entries(id, workspace_id, board_id, card_id, actor_user_id, kind, entity_type, entity_id, payload_json, occurred_at) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
        params![value.id.as_str(), value.workspace_id.as_str(), value.board_id.as_str(), value.card_id.as_ref().map(CardId::as_str), value.actor_user_id, value.kind, value.entity_type, value.entity_id, value.payload_json, value.occurred_at],
    ).map_err(storage)?;
    Ok(())
}

fn record_unsupported(tx: &Transaction<'_>, workspace_id: &WorkspaceId, board_id: &BoardId, kind: &str, entity_id: &str) -> Result<(), ParityRepositoryError> {
    tx.execute(
        "INSERT INTO parity_local_changes(id,workspace_id,board_id,kind,entity_id,reason,created_at_unix_ms) VALUES (?1,?2,?3,?4,?5,'roaming-v1-unsupported',?6)",
        params![Uuid::new_v4().to_string(), workspace_id.as_str(), board_id.as_str(), kind, entity_id, now_millis()],
    ).map_err(storage)?;
    Ok(())
}

fn next_local_clock(tx: &Transaction<'_>) -> Result<u64, ParityRepositoryError> {
    let current: String = tx.query_row("SELECT logical_clock FROM local_mutation_state WHERE singleton=1", [], |row| row.get(0)).map_err(storage)?;
    let next = current.parse::<u64>().map_err(storage)?.checked_add(1).ok_or(ParityRepositoryError::StorageFailure)?;
    tx.execute("UPDATE local_mutation_state SET logical_clock=?1 WHERE singleton=1", [next.to_string()]).map_err(storage)?;
    Ok(next)
}

fn enqueue_appearance(tx: &Transaction<'_>, workspace_id: &WorkspaceId, board_id: &BoardId) -> Result<(), ParityRepositoryError> {
    let sequence = next_local_clock(tx)?;
    tx.execute(
        "INSERT INTO pending_local_changes(id,workspace_id,board_id,sequence,kind,entity_id,created_at_unix_ms) VALUES (?1,?2,?3,?4,'board.appearance.put',?5,?6)",
        params![Uuid::new_v4().to_string(), workspace_id.as_str(), board_id.as_str(), sequence.to_string(), board_id.as_str(), now_millis()],
    ).map_err(storage)?;
    Ok(())
}

fn parse_label(row: &rusqlite::Row<'_>) -> rusqlite::Result<(String,String,String,Option<String>,f64,String)> {
    Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?))
}

impl ParityRepository for SqliteParityRepository {
    fn board_workspace(&self, board_id: &BoardId) -> Result<WorkspaceId, ParityRepositoryError> { board_workspace_on(&self.connection, board_id) }

    fn card_scope(&self, card_id: &CardId) -> Result<(WorkspaceId, BoardId), ParityRepositoryError> { card_scope_on(&self.connection, card_id) }

    fn list_labels(&self, board_id: &BoardId) -> Result<Vec<LabelRecord>, ParityRepositoryError> {
        board_workspace_on(&self.connection, board_id)?;
        let mut stmt=self.connection.prepare("SELECT id,board_id,name,color,position,raw_json FROM labels WHERE board_id=?1 ORDER BY position,id").map_err(storage)?;
        let rows=stmt.query_map([board_id.as_str()],parse_label).map_err(storage)?;
        let mut values=Vec::new();
        for row in rows { let (id,board,name,color,position,raw)=row.map_err(storage)?; values.push(LabelRecord{id:LabelId::new(id).map_err(storage)?,board_id:BoardId::new(board).map_err(storage)?,name,color,position:OrderKey::new(position).map_err(storage)?,raw_json:raw}); }
        Ok(values)
    }

    fn create_label(&mut self, workspace_id: &WorkspaceId, label: LabelRecord, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError> {
        if board_workspace_on(&self.connection,&label.board_id)? != *workspace_id { return Err(ParityRepositoryError::ScopeMismatch); }
        let tx=self.connection.transaction_with_behavior(TransactionBehavior::Immediate).map_err(storage)?;
        tx.execute("INSERT INTO labels(id,board_id,name,color,position,raw_json) VALUES (?1,?2,?3,?4,?5,?6)",params![label.id.as_str(),label.board_id.as_str(),label.name,label.color,label.position.get(),label.raw_json])
            .map_err(|e|constraint(e,ParityRepositoryError::DuplicateLabel))?;
        record_unsupported(&tx,workspace_id,&label.board_id,"label.create",label.id.as_str())?;
        insert_activity(&tx,activity)?;
        tx.commit().map_err(storage)
    }

    fn delete_label(&mut self, workspace_id: &WorkspaceId, board_id: &BoardId, label_id: &LabelId, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError> {
        if board_workspace_on(&self.connection,board_id)? != *workspace_id { return Err(ParityRepositoryError::ScopeMismatch); }
        let tx=self.connection.transaction_with_behavior(TransactionBehavior::Immediate).map_err(storage)?;
        let changed=tx.execute("DELETE FROM labels WHERE id=?1 AND board_id=?2",params![label_id.as_str(),board_id.as_str()]).map_err(storage)?;
        if changed==0 { return Err(ParityRepositoryError::LabelNotFound); }
        record_unsupported(&tx,workspace_id,board_id,"label.delete",label_id.as_str())?;
        insert_activity(&tx,activity)?;
        tx.commit().map_err(storage)
    }

    fn list_card_labels(&self, card_id: &CardId) -> Result<Vec<CardLabelRecord>, ParityRepositoryError> {
        card_scope_on(&self.connection,card_id)?;
        let mut stmt=self.connection.prepare("SELECT label_id FROM card_labels WHERE card_id=?1 ORDER BY label_id").map_err(storage)?;
        let rows=stmt.query_map([card_id.as_str()],|row|row.get::<_,String>(0)).map_err(storage)?;
        let mut values=Vec::new(); for row in rows { values.push(CardLabelRecord{card_id:card_id.clone(),label_id:LabelId::new(row.map_err(storage)?).map_err(storage)?}); } Ok(values)
    }

    fn set_card_label(&mut self, workspace_id: &WorkspaceId, board_id: &BoardId, edge: CardLabelRecord, assigned: bool, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError> {
        let (card_workspace,card_board)=card_scope_on(&self.connection,&edge.card_id)?;
        if card_workspace!=*workspace_id || card_board!=*board_id { return Err(ParityRepositoryError::ScopeMismatch); }
        let label_board:Option<String>=self.connection.query_row("SELECT board_id FROM labels WHERE id=?1",[edge.label_id.as_str()],|row|row.get(0)).optional().map_err(storage)?;
        match label_board { None=>return Err(ParityRepositoryError::LabelNotFound),Some(value) if value!=board_id.as_str()=>return Err(ParityRepositoryError::ScopeMismatch),_=>{} }
        let tx=self.connection.transaction_with_behavior(TransactionBehavior::Immediate).map_err(storage)?;
        if assigned { tx.execute("INSERT OR IGNORE INTO card_labels(card_id,label_id) VALUES (?1,?2)",params![edge.card_id.as_str(),edge.label_id.as_str()]).map_err(storage)?; }
        else { tx.execute("DELETE FROM card_labels WHERE card_id=?1 AND label_id=?2",params![edge.card_id.as_str(),edge.label_id.as_str()]).map_err(storage)?; }
        record_unsupported(&tx,workspace_id,board_id,if assigned{"card.label.assign"}else{"card.label.unassign"},edge.card_id.as_str())?;
        insert_activity(&tx,activity)?;
        tx.commit().map_err(storage)
    }

    fn list_comments(&self, card_id: &CardId) -> Result<Vec<CommentRecord>, ParityRepositoryError> {
        card_scope_on(&self.connection,card_id)?;
        let mut stmt=self.connection.prepare("SELECT id,workspace_id,board_id,card_id,author_user_id,body,created_at,updated_at,raw_json FROM comments WHERE card_id=?1 ORDER BY created_at,id").map_err(storage)?;
        let rows=stmt.query_map([card_id.as_str()],|row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,String>(3)?,row.get::<_,Option<String>>(4)?,row.get::<_,String>(5)?,row.get::<_,String>(6)?,row.get::<_,String>(7)?,row.get::<_,String>(8)?))).map_err(storage)?;
        let mut values=Vec::new();
        for row in rows { let (id,w,b,c,author,body,created,updated,raw)=row.map_err(storage)?; values.push(CommentRecord{id:CommentId::new(id).map_err(storage)?,workspace_id:WorkspaceId::new(w).map_err(storage)?,board_id:BoardId::new(b).map_err(storage)?,card_id:CardId::new(c).map_err(storage)?,author_user_id:author,body,created_at:created,updated_at:updated,raw_json:raw}); }
        Ok(values)
    }

    fn comment_board(&self, comment_id: &CommentId, workspace_id: &WorkspaceId) -> Result<BoardId, ParityRepositoryError> {
        let row:Option<(String,String)>=self.connection.query_row("SELECT workspace_id,board_id FROM comments WHERE id=?1",[comment_id.as_str()],|row|Ok((row.get(0)?,row.get(1)?))).optional().map_err(storage)?;
        let (workspace,board)=row.ok_or(ParityRepositoryError::CommentNotFound)?;
        if workspace!=workspace_id.as_str(){return Err(ParityRepositoryError::ScopeMismatch);} BoardId::new(board).map_err(storage)
    }

    fn create_comment(&mut self, comment: CommentRecord, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError> {
        let (workspace,board)=card_scope_on(&self.connection,&comment.card_id)?;
        if workspace!=comment.workspace_id || board!=comment.board_id {return Err(ParityRepositoryError::ScopeMismatch);}
        let tx=self.connection.transaction_with_behavior(TransactionBehavior::Immediate).map_err(storage)?;
        tx.execute("INSERT INTO comments(id,workspace_id,board_id,card_id,author_user_id,body,created_at,updated_at,raw_json) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",params![comment.id.as_str(),comment.workspace_id.as_str(),comment.board_id.as_str(),comment.card_id.as_str(),comment.author_user_id,comment.body,comment.created_at,comment.updated_at,comment.raw_json]).map_err(|e|constraint(e,ParityRepositoryError::DuplicateComment))?;
        record_unsupported(&tx,&comment.workspace_id,&comment.board_id,"comment.create",comment.id.as_str())?;
        insert_activity(&tx,activity)?; tx.commit().map_err(storage)
    }

    fn delete_comment(&mut self, workspace_id: &WorkspaceId, board_id: &BoardId, comment_id: &CommentId, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError> {
        let tx=self.connection.transaction_with_behavior(TransactionBehavior::Immediate).map_err(storage)?;
        let changed=tx.execute("DELETE FROM comments WHERE id=?1 AND workspace_id=?2 AND board_id=?3",params![comment_id.as_str(),workspace_id.as_str(),board_id.as_str()]).map_err(storage)?;
        if changed==0{return Err(ParityRepositoryError::CommentNotFound);} record_unsupported(&tx,workspace_id,board_id,"comment.delete",comment_id.as_str())?; insert_activity(&tx,activity)?; tx.commit().map_err(storage)
    }

    fn get_appearance(&self, board_id: &BoardId) -> Result<Option<BoardAppearanceRecord>, ParityRepositoryError> {
        board_workspace_on(&self.connection,board_id)?;
        let row:Option<(String,String)>=self.connection.query_row("SELECT settings_json,updated_at FROM board_appearance_settings WHERE board_id=?1",[board_id.as_str()],|row|Ok((row.get(0)?,row.get(1)?))).optional().map_err(storage)?;
        row.map(|(settings,updated)|Ok(BoardAppearanceRecord{board_id:board_id.clone(),settings_json:settings,updated_at:updated})).transpose()
    }

    fn set_appearance(&mut self, workspace_id: &WorkspaceId, appearance: BoardAppearanceRecord, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError> {
        if board_workspace_on(&self.connection,&appearance.board_id)? != *workspace_id{return Err(ParityRepositoryError::ScopeMismatch);}
        let tx=self.connection.transaction_with_behavior(TransactionBehavior::Immediate).map_err(storage)?;
        tx.execute("INSERT INTO board_appearance_settings(board_id,settings_json,updated_at) VALUES (?1,?2,?3) ON CONFLICT(board_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at",params![appearance.board_id.as_str(),appearance.settings_json,appearance.updated_at]).map_err(storage)?;
        enqueue_appearance(&tx,workspace_id,&appearance.board_id)?; insert_activity(&tx,activity)?; tx.commit().map_err(storage)
    }

    fn list_activity(&self, board_id: &BoardId, limit: usize) -> Result<Vec<ActivityEntryRecord>, ParityRepositoryError> {
        board_workspace_on(&self.connection,board_id)?;
        let mut stmt=self.connection.prepare("SELECT id,workspace_id,board_id,card_id,actor_user_id,kind,entity_type,entity_id,payload_json,occurred_at FROM activity_entries WHERE board_id=?1 ORDER BY occurred_at DESC,id DESC LIMIT ?2").map_err(storage)?;
        let rows=stmt.query_map(params![board_id.as_str(),limit as i64],|row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,Option<String>>(3)?,row.get::<_,Option<String>>(4)?,row.get::<_,String>(5)?,row.get::<_,String>(6)?,row.get::<_,Option<String>>(7)?,row.get::<_,String>(8)?,row.get::<_,String>(9)?))).map_err(storage)?;
        let mut values=Vec::new(); for row in rows {let(id,w,b,c,actor,kind,entity_type,entity_id,payload,at)=row.map_err(storage)?;values.push(ActivityEntryRecord{id:ActivityEntryId::new(id).map_err(storage)?,workspace_id:WorkspaceId::new(w).map_err(storage)?,board_id:BoardId::new(b).map_err(storage)?,card_id:c.map(CardId::new).transpose().map_err(storage)?,actor_user_id:actor,kind,entity_type,entity_id,payload_json:payload,occurred_at:at});} Ok(values)
    }

    fn unsynced_parity_count(&self, board_id: &BoardId) -> Result<u64, ParityRepositoryError> {
        board_workspace_on(&self.connection,board_id)?; let count:i64=self.connection.query_row("SELECT COUNT(*) FROM parity_local_changes WHERE board_id=?1",[board_id.as_str()],|row|row.get(0)).map_err(storage)?; u64::try_from(count).map_err(storage)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::parity::{ParityService, RandomParityIds};
    use crate::infrastructure::profile::ProfileStoragePaths;
    use std::{fs,path::PathBuf,sync::atomic::{AtomicU64,Ordering}};

    static NEXT:AtomicU64=AtomicU64::new(1);
    fn temp_profile(name:&str)->ProfileStoragePaths{let n=NEXT.fetch_add(1,Ordering::Relaxed);ProfileStoragePaths::new(std::env::temp_dir().join(format!("p2pkanban-a12-{name}-{}-{n}/profiles/default",std::process::id())))}
    fn cleanup(layout:&ProfileStoragePaths){let root=layout.root().ancestors().nth(2).map(PathBuf::from).unwrap_or_else(||layout.root().to_path_buf());let _=fs::remove_dir_all(root);}
    fn seed(repo:&SqliteParityRepository){repo.connection.execute("INSERT INTO workspaces(id,title,access_epoch) VALUES ('workspace-a','w','1')",[]).unwrap();repo.connection.execute("INSERT INTO boards(id,workspace_id,title) VALUES ('board-a','workspace-a','b')",[]).unwrap();repo.connection.execute("INSERT INTO columns(id,board_id,title,position) VALUES ('column-a','board-a','todo',1000)",[]).unwrap();repo.connection.execute("INSERT INTO cards(id,workspace_id,board_id,column_id,title,position,lifecycle) VALUES ('card-a','workspace-a','board-a','column-a','c',1000,'active')",[]).unwrap();}

    #[test]
    fn a12_local_label_comment_activity_are_atomic_and_explicitly_unsynced(){let layout=temp_profile("local");cleanup(&layout);{let repo=SqliteParityRepository::open(&layout).unwrap();seed(&repo);}let service=ParityService::new(Box::new(SqliteParityRepository::open(&layout).unwrap()),Box::new(RandomParityIds));let label=service.create_label("workspace-a","board-a","urgent",Some("red")).unwrap();service.set_card_label("workspace-a","card-a",&label.id,true).unwrap();let comment=service.create_comment("workspace-a","card-a","hello").unwrap();assert_eq!(service.list_comments("workspace-a","card-a").unwrap()[0].body,"hello");service.delete_comment("workspace-a",&comment.id).unwrap();assert!(service.unsynced_parity_count("workspace-a","board-a").unwrap()>=4);assert!(service.list_activity("workspace-a","board-a",20).unwrap().len()>=4);cleanup(&layout);}

    #[test]
    fn a12_appearance_is_durable_and_uses_existing_roaming_pending_kind(){let layout=temp_profile("appearance");cleanup(&layout);{let repo=SqliteParityRepository::open(&layout).unwrap();seed(&repo);}let service=ParityService::new(Box::new(SqliteParityRepository::open(&layout).unwrap()),Box::new(RandomParityIds));let value=service.set_appearance("workspace-a","board-a",r#"{"accent":"violet"}"#).unwrap();assert!(value.settings_json.contains("boardId"));let repo=SqliteParityRepository::open(&layout).unwrap();let kind:String=repo.connection.query_row("SELECT kind FROM pending_local_changes",[],|row|row.get(0)).unwrap();assert_eq!(kind,"board.appearance.put");cleanup(&layout);}
}
