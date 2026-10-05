-- Full-card roaming snapshots from beta.8 marked every field as changed.
-- Any winning snapshot therefore looked like a move and could replace a newer
-- checklist with an older array. Beta.9 uses entity deltas; remove the
-- unmistakable legacy noise from the readable history.
delete from activity_entries
where kind = 'card.moved'
  and payload_jsonb ->> 'source' = 'roaming'
  and field_mask @> array['checklists']::text[];

update replicas
set app_version = '1.0.0-beta.9'
where id in (select replica_id from local_node_identity)
  and replica_kind = 'server';

