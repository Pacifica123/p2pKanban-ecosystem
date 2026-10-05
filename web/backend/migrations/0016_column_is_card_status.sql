-- Card state is represented only by board column membership. Remove the old
-- fixed lifecycle from storage as well as from the beta.11 domain and wire
-- contracts: leaving nullable shadows would keep two competing meanings alive.
alter table cards drop constraint if exists chk_cards_completed_at;
alter table cards drop constraint if exists chk_cards_status;
drop index if exists idx_cards_board_completed_at;
alter table cards drop column status;
alter table cards drop column completed_at;

update replicas
set app_version = '1.0.0-beta.11'
where id in (select replica_id from local_node_identity)
  and replica_kind = 'server';
