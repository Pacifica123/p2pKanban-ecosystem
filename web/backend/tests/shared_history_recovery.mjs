import fs from 'node:fs';
import assert from 'node:assert/strict';

// Pass a disposable PGlite/PostgreSQL adapter with exec() and query().
// All migrations and fixture mutations execute only in that disposable database.
export async function verifySharedRecovery(db, root) {
const files=fs.readdirSync(root+'/migrations').filter(v=>v.endsWith('.sql')).sort();
assert.equal(new Set(files.map(x=>x.split('_')[0])).size,files.length,'migration ids must be unique');
for(const f of files)await db.exec(fs.readFileSync(root+'/migrations/'+f,'utf8'));
const uid=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const [user,workspace,board,column,card,list,item,replica,eid]=[1,2,3,4,5,6,7,8,9].map(uid);
await db.exec(`insert into users(id,email,display_name) values('${user}','test@example.invalid','Test');
insert into workspaces(id,name,owner_user_id) values('${workspace}','Workspace','${user}');
insert into boards(id,workspace_id,name) values('${board}','${workspace}','Board');
insert into board_columns(id,board_id,name,position) values('${column}','${board}','Column',1);
insert into cards(id,board_id,column_id,title,position) values('${card}','${board}','${column}','Card',1);
insert into checklists(id,card_id,title,position) values('${list}','${card}','List',1);
insert into checklist_items(id,checklist_id,title,position) values('${item}','${list}','Item',1);`);
const make=done=>({checklistsByCardId:{[card]:[{id:list,cardId:card,title:'List',position:1,items:[{id:item,checklistId:list,title:'Item',position:1,isDone:done}]}]}});
const stamp=n=>({logicalClock:n,replicaId:replica,eventId:eid});
const apply=(snapshot,versions)=>db.query('select merge_roaming_checklist_versions($1,$2,$3,$4)',[workspace,board,snapshot,versions]);
const read=async()=> (await db.query('select is_done,deleted_at from checklist_items where id=$1',[item])).rows[0];
await apply(make(true),{[item+':checklist_item.isDone']:stamp(20)});assert.equal((await read()).is_done,true);console.log('PASS snapshot repairs existing item');
await apply(make(false),{[item+':checklist_item.isDone']:stamp(10)});assert.equal((await read()).is_done,true);console.log('PASS stale snapshot cannot cancel newer toggle');
await apply(make(false),{});assert.equal((await read()).is_done,true);console.log('PASS unversioned legacy snapshot cannot overwrite item');
await apply(make(false),{[item+':checklist_item.isDone']:stamp(30)});assert.equal((await read()).is_done,false);console.log('PASS newer reopen clears completed_at');
const empty=make(false);empty.checklistsByCardId[card][0].items=[];
await apply(empty,{[item+':checklist_item.__lifecycle']:stamp(40)});assert.ok((await read()).deleted_at);console.log('PASS explicit recovery tombstone deletes item');
await apply(make(true),{[item+':checklist_item.__lifecycle']:stamp(35)});assert.ok((await read()).deleted_at);console.log('PASS stale snapshot cannot resurrect deleted item');
await apply(make(true),{[item+':checklist_item.__lifecycle']:stamp(50),[item+':checklist_item.isDone']:stamp(50)});assert.equal((await read()).deleted_at,null);console.log('PASS newer lifecycle can restore item');
const aid=uid(30), remoteId=uid(31);
await db.query(`insert into activity_entries(id,workspace_id,board_id,card_id,actor_user_id,kind,entity_type,entity_id,field_mask,payload_jsonb)
 values($1,$2,$3,$4,$5,'comment.created','comment',$6,array['body'],'{}')`,[aid,workspace,board,card,user,uid(32)]);
await db.query(`insert into activity_entries(id,workspace_id,board_id,card_id,actor_user_id,kind,entity_type,entity_id,payload_jsonb)
 values($1,$2,$3,$4,$5,'card.updated','card',$4,'{"source":"roaming","commonHistory":true}')`,[remoteId,workspace,board,card,user]);
const rust=fs.readFileSync(root+'/src/transports/roaming_history.rs','utf8');
const queries=[...rust.matchAll(/sqlx::query\(r#"([\s\S]*?)"#\)/g)].map(x=>x[1]);
const originals=await db.query(queries[0],[100]);assert.equal(originals.rows.length,2);console.log('PASS real worker query backfills original comments and imported canonical history');
const fakeWire={capabilityEpoch:1,eventId:uid(50),payload:{activity:{id:aid}}};
await db.query('insert into roaming_activity_outbox(activity_id,capability_epoch,event_json) values($1,1,$2)',[aid,fakeWire]);
assert.equal((await db.query(queries[0],[100])).rows.length,1);console.log('PASS frozen history is not enqueued again at same epoch');
await db.query('update workspaces set access_epoch=2 where id=$1',[workspace]);
assert.equal((await db.query(queries[0],[100])).rows.length,2);console.log('PASS new access epoch can recover historical actions under new keys');

}
