-- Explicitly approved account peers; invitations contain no account password.
create table trusted_device_peers (
 user_id uuid not null references users(id) on delete cascade,
 public_key text not null check(length(public_key)=64),
 approved_at timestamptz not null default now(),
 primary key(user_id,public_key)
);
create table device_link_lan_inbox (
 id text primary key,
 request_json jsonb not null,
 response_json jsonb,
 expires_at bigint not null,
 approved_at timestamptz
);
create table device_link_lan_outbound (
 id text primary key references device_link_challenges(id) on delete cascade,
 peer_url text not null
);
alter table device_link_challenges add column lan_mobile_response jsonb;
