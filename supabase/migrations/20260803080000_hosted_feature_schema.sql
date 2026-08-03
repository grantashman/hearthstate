create table if not exists public.profiles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    email text,
    display_name text not null default 'Household member' check (char_length(trim(display_name)) between 1 and 120),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.planner_settings (
    household_id uuid primary key references public.households(id) on delete cascade,
    weekly_budget numeric(10,2) check (weekly_budget is null or weekly_budget >= 0),
    updated_by uuid references auth.users(id) on delete set null,
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.recipes (
    id uuid primary key default gen_random_uuid(),
    household_id uuid not null references public.households(id) on delete cascade,
    source text not null default 'user_supplied',
    source_policy text not null default 'user_supplied',
    title text not null check (char_length(trim(title)) between 1 and 500),
    source_url text not null,
    image_url text,
    summary text not null default '',
    tags jsonb not null default '[]'::jsonb check (jsonb_typeof(tags) = 'array'),
    prep_minutes integer,
    cook_minutes integer,
    ingredients jsonb not null default '[]'::jsonb check (jsonb_typeof(ingredients) = 'array'),
    created_by uuid not null references auth.users(id) on delete restrict,
    created_at timestamptz not null default timezone('utc', now()),
    unique (household_id, source_url)
);

create table if not exists public.saved_recipes (
    recipe_id uuid not null references public.recipes(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    saved_at timestamptz not null default timezone('utc', now()),
    primary key (recipe_id, user_id)
);

create table if not exists public.notification_preferences (
    household_id uuid not null references public.households(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    briefing_type text not null default 'morning' check (briefing_type in ('morning', 'evening', 'weekly')),
    enabled boolean not null default true,
    preferred_time text not null default '07:00',
    quiet_start text not null default '21:00',
    quiet_end text not null default '07:00',
    channel text not null default 'email' check (channel in ('email', 'none')),
    updated_at timestamptz not null default timezone('utc', now()),
    primary key (household_id, user_id, briefing_type)
);

create table if not exists public.chore_templates (
    id uuid primary key default gen_random_uuid(),
    household_id uuid not null references public.households(id) on delete cascade,
    title text not null check (char_length(trim(title)) between 1 and 300),
    cadence text not null default 'weekly',
    participants jsonb not null default '[]'::jsonb check (jsonb_typeof(participants) = 'array'),
    next_index integer not null default 0 check (next_index >= 0),
    active boolean not null default true,
    created_by uuid not null references auth.users(id) on delete restrict,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.invitations (
    id uuid primary key default gen_random_uuid(),
    household_id uuid not null references public.households(id) on delete cascade,
    email text not null check (char_length(trim(email)) between 3 and 320),
    role text not null default 'member' check (role in ('member', 'child', 'guest')),
    token_hash text not null unique,
    invited_by uuid not null references auth.users(id) on delete restrict,
    expires_at timestamptz not null,
    accepted_at timestamptz,
    accepted_user_id uuid references auth.users(id) on delete set null,
    revoked_at timestamptz,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists profiles_email_idx on public.profiles(email);
create index if not exists recipes_household_created_idx on public.recipes(household_id, created_at desc);
create index if not exists invitations_household_status_idx on public.invitations(household_id, created_at desc);
create index if not exists chore_templates_household_active_idx on public.chore_templates(household_id, active);

alter table public.profiles enable row level security;
alter table public.planner_settings enable row level security;
alter table public.recipes enable row level security;
alter table public.saved_recipes enable row level security;
alter table public.notification_preferences enable row level security;
alter table public.chore_templates enable row level security;
alter table public.invitations enable row level security;

drop policy if exists profiles_self_or_member_select on public.profiles;
create policy profiles_self_or_member_select on public.profiles for select to authenticated using (user_id = (select auth.uid()) or exists (select 1 from public.memberships mine join public.memberships theirs on theirs.household_id = mine.household_id where mine.user_id = (select auth.uid()) and theirs.user_id = profiles.user_id));
drop policy if exists profiles_self_insert on public.profiles;
create policy profiles_self_insert on public.profiles for insert to authenticated with check (user_id = (select auth.uid()));
drop policy if exists profiles_self_update on public.profiles;
create policy profiles_self_update on public.profiles for update to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists planner_settings_member_select on public.planner_settings;
create policy planner_settings_member_select on public.planner_settings for select to authenticated using (private.is_household_member(household_id));
drop policy if exists planner_settings_member_write on public.planner_settings;
create policy planner_settings_member_write on public.planner_settings for insert to authenticated with check (private.is_household_member(household_id) and updated_by = (select auth.uid()));
drop policy if exists planner_settings_owner_update on public.planner_settings;
create policy planner_settings_owner_update on public.planner_settings for update to authenticated using (private.is_household_member(household_id)) with check (private.is_household_member(household_id) and updated_by = (select auth.uid()));

drop policy if exists recipes_member_select on public.recipes;
create policy recipes_member_select on public.recipes for select to authenticated using (private.is_household_member(household_id));
drop policy if exists recipes_member_insert on public.recipes;
create policy recipes_member_insert on public.recipes for insert to authenticated with check (private.is_household_member(household_id) and created_by = (select auth.uid()));
drop policy if exists recipes_member_update on public.recipes;
create policy recipes_member_update on public.recipes for update to authenticated using (private.is_household_member(household_id)) with check (private.is_household_member(household_id));
drop policy if exists recipes_member_delete on public.recipes;
create policy recipes_member_delete on public.recipes for delete to authenticated using (private.is_household_member(household_id) and (created_by = (select auth.uid()) or private.is_household_owner(household_id)));

drop policy if exists saved_recipes_member_select on public.saved_recipes;
create policy saved_recipes_member_select on public.saved_recipes for select to authenticated using (user_id = (select auth.uid()) or exists (select 1 from public.recipes where recipes.id = saved_recipes.recipe_id and private.is_household_member(recipes.household_id)));
drop policy if exists saved_recipes_self_write on public.saved_recipes;
create policy saved_recipes_self_write on public.saved_recipes for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists notification_preferences_self on public.notification_preferences;
create policy notification_preferences_self on public.notification_preferences for all to authenticated using (user_id = (select auth.uid()) and private.is_household_member(household_id)) with check (user_id = (select auth.uid()) and private.is_household_member(household_id));

drop policy if exists chores_member_select on public.chore_templates;
create policy chores_member_select on public.chore_templates for select to authenticated using (private.is_household_member(household_id));
drop policy if exists chores_member_write on public.chore_templates;
create policy chores_member_write on public.chore_templates for all to authenticated using (private.is_household_member(household_id)) with check (private.is_household_member(household_id) and created_by = (select auth.uid()));

drop policy if exists invitations_owner_select on public.invitations;
create policy invitations_owner_select on public.invitations for select to authenticated using (private.is_household_owner(household_id));
drop policy if exists invitations_owner_write on public.invitations;
create policy invitations_owner_write on public.invitations for all to authenticated using (private.is_household_owner(household_id)) with check (private.is_household_owner(household_id) and invited_by = (select auth.uid()));

grant select, insert, update on public.profiles to authenticated;
grant select, insert, update on public.planner_settings to authenticated;
grant select, insert, update, delete on public.recipes to authenticated;
grant select, insert, update, delete on public.saved_recipes to authenticated;
grant select, insert, update, delete on public.notification_preferences to authenticated;
grant select, insert, update, delete on public.chore_templates to authenticated;
grant select, insert, update, delete on public.invitations to authenticated;

create or replace function public.inspect_invitation(raw_token text)
returns table (email text, role text, household_id uuid, household_name text, expires_at timestamptz)
language sql stable security definer set search_path = public, extensions as $$
    select i.email, i.role, i.household_id, h.name, i.expires_at
    from public.invitations i join public.households h on h.id = i.household_id
    where i.token_hash = encode(digest(raw_token, 'sha256'), 'hex') and i.revoked_at is null and i.accepted_at is null and i.expires_at > timezone('utc', now()) limit 1;
$$;
revoke all on function public.inspect_invitation(text) from public;
grant execute on function public.inspect_invitation(text) to anon, authenticated;

create or replace function public.accept_invitation(raw_token text, display_name text)
returns public.memberships language plpgsql security definer set search_path = public, extensions as $$
declare invitation public.invitations; created_membership public.memberships; invite_email text := lower(trim(coalesce((select auth.jwt() ->> 'email'), '')));
begin
    if auth.uid() is null then raise exception 'authentication required' using errcode = '42501'; end if;
    select i.* into invitation from public.invitations i where i.token_hash = encode(digest(raw_token, 'sha256'), 'hex') and i.revoked_at is null and i.accepted_at is null and i.expires_at > timezone('utc', now()) for update;
    if not found then raise exception 'invitation is invalid or expired' using errcode = '22023'; end if;
    if lower(trim(invitation.email)) <> invite_email then raise exception 'invitation email does not match sign-in email' using errcode = '42501'; end if;
    insert into public.memberships (household_id, user_id, role) values (invitation.household_id, auth.uid(), invitation.role) on conflict (household_id, user_id) do update set role = excluded.role returning * into created_membership;
    update public.invitations set accepted_at = timezone('utc', now()), accepted_user_id = auth.uid() where id = invitation.id;
    insert into public.profiles (user_id, email, display_name) values (auth.uid(), invite_email, coalesce(nullif(trim(display_name), ''), split_part(invite_email, '@', 1))) on conflict (user_id) do update set email = excluded.email, display_name = excluded.display_name, updated_at = timezone('utc', now());
    return created_membership;
end;
$$;
revoke all on function public.accept_invitation(text, text) from public;
grant execute on function public.accept_invitation(text, text) to authenticated;
