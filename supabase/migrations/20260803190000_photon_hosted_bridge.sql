-- Trusted Photon bridge for the hosted Hearthstate API.
-- The bridge token is never stored in plaintext; only its SHA-256 digest is kept here.
create table if not exists public.channel_integrations (
    id uuid primary key default gen_random_uuid(),
    channel text not null check (channel in ('photon')),
    name text not null,
    token_hash text not null unique,
    allowed_email text not null check (char_length(trim(allowed_email)) between 3 and 320),
    enabled boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    unique (channel, name)
);

create table if not exists public.channel_identities (
    integration_id uuid not null references public.channel_integrations(id) on delete cascade,
    external_user_id text not null check (char_length(trim(external_user_id)) between 8 and 64),
    user_id uuid not null references auth.users(id) on delete cascade,
    household_id uuid not null references public.households(id) on delete cascade,
    created_at timestamptz not null default timezone('utc', now()),
    primary key (integration_id, external_user_id)
);

create index if not exists channel_identities_user_idx
    on public.channel_identities(integration_id, user_id, household_id);

alter table public.channel_integrations enable row level security;
alter table public.channel_identities enable row level security;

revoke all on public.channel_integrations from anon, authenticated;
revoke all on public.channel_identities from anon, authenticated;
grant select, insert, update, delete on public.channel_integrations to service_role;
grant select, insert, update, delete on public.channel_identities to service_role;

insert into public.channel_integrations (channel, name, token_hash, allowed_email)
values (
    'photon',
    'Hearthstate Photon bridge',
    '3b00cad2611a5fa21ee285e101a4d9cebc4c326beb897e611303d7562517444c',
    'grant@ashman.net.au'
)
on conflict (channel, name) do update
set token_hash = excluded.token_hash,
    allowed_email = excluded.allowed_email,
    enabled = true;

-- Bind immediately when the hosted profile already exists. The protected
-- identity endpoint can repeat this idempotently after first sign-in.
insert into public.channel_identities (integration_id, external_user_id, user_id, household_id)
select integration.id, '+61400025889', profile.user_id, membership.household_id
from public.channel_integrations integration
join public.profiles profile on lower(profile.email) = 'grant@ashman.net.au'
join lateral (
    select m.household_id
    from public.memberships m
    where m.user_id = profile.user_id
    order by m.created_at asc
    limit 1
) membership on true
where integration.channel = 'photon'
  and integration.name = 'Hearthstate Photon bridge'
on conflict (integration_id, external_user_id) do update
set user_id = excluded.user_id,
    household_id = excluded.household_id;
