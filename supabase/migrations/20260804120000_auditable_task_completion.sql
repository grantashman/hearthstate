create or replace function public.complete_task(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_task_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    actor_membership public.memberships;
    task_row public.tasks;
    completed_task public.tasks;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;

    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;

    select * into task_row
    from public.tasks
    where id = p_task_id and household_id = p_household_id
    for update;
    if not found then
        raise exception 'task not found' using errcode = 'P0002';
    end if;
    if task_row.private and task_row.owner is distinct from p_actor_user_id and task_row.created_by is distinct from p_actor_user_id then
        raise exception 'private task access denied' using errcode = '42501';
    end if;
    if task_row.status <> 'open' then
        raise exception 'task is not open' using errcode = '22023';
    end if;

    update public.tasks
    set status = 'done'
    where id = p_task_id and household_id = p_household_id and status = 'open'
    returning * into completed_task;

    insert into public.activity_log (
        household_id,
        actor,
        action,
        entity_type,
        entity_id,
        after_json
    ) values (
        p_household_id,
        p_actor_user_id,
        'task.completed',
        'task',
        p_task_id,
        jsonb_build_object('id', p_task_id, 'status', 'done')
    );

    return to_jsonb(completed_task);
end;
$$;

revoke all on function public.complete_task(uuid, uuid, uuid) from public;
grant execute on function public.complete_task(uuid, uuid, uuid) to authenticated, service_role;

drop policy if exists tasks_member_update on public.tasks;
create policy tasks_member_update on public.tasks for update to authenticated
using (
    status <> 'done'
    and private.is_household_member(household_id)
    and (not private or owner = (select auth.uid()) or created_by = (select auth.uid()))
)
with check (
    status <> 'done'
    and private.is_household_member(household_id)
    and (not private or owner = (select auth.uid()) or created_by = (select auth.uid()))
);

drop policy if exists tasks_member_insert on public.tasks;
create policy tasks_member_insert on public.tasks for insert to authenticated
with check (
    status <> 'done'
    and private.is_household_member(household_id)
    and created_by = (select auth.uid())
);

create or replace function public.create_task(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_title text,
    p_due_at timestamptz default null,
    p_owner uuid default null,
    p_assignee uuid default null,
    p_private boolean default false,
    p_recurrence text default 'none'
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    created_task public.tasks;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    perform 1 from public.memberships
    where household_id = p_household_id
      and user_id in (p_actor_user_id, p_owner, p_assignee)
    order by user_id
    for update;
    if not exists (select 1 from public.memberships where household_id = p_household_id and user_id = p_actor_user_id) then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if p_owner is not null and not exists (select 1 from public.memberships where household_id = p_household_id and user_id = p_owner) then
        raise exception 'task owner must be a household member' using errcode = '22023';
    end if;
    if p_assignee is not null and not exists (select 1 from public.memberships where household_id = p_household_id and user_id = p_assignee) then
        raise exception 'task assignee must be a household member' using errcode = '22023';
    end if;
    if char_length(trim(coalesce(p_title, ''))) not between 1 and 500 then
        raise exception 'task title is required' using errcode = '22023';
    end if;
    if coalesce(p_recurrence, 'none') not in ('none', 'daily', 'weekly', 'fortnightly', 'monthly', 'yearly') then
        raise exception 'invalid task recurrence' using errcode = '22023';
    end if;
    insert into public.tasks (household_id, title, due_at, owner, assignee, private, recurrence, status, created_by)
    values (p_household_id, trim(p_title), p_due_at, p_owner, p_assignee, coalesce(p_private, false), coalesce(p_recurrence, 'none'), 'open', p_actor_user_id)
    returning * into created_task;
    return to_jsonb(created_task);
end;
$$;

create or replace function public.create_event(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_title text,
    p_starts_at timestamptz,
    p_ends_at timestamptz default null,
    p_person text default null,
    p_assignee uuid default null
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    created_event public.events;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    perform 1 from public.memberships
    where household_id = p_household_id and user_id in (p_actor_user_id, p_assignee)
    order by user_id
    for update;
    if not exists (select 1 from public.memberships where household_id = p_household_id and user_id = p_actor_user_id) then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if p_assignee is not null and not exists (select 1 from public.memberships where household_id = p_household_id and user_id = p_assignee) then
        raise exception 'event assignee must be a household member' using errcode = '22023';
    end if;
    if char_length(trim(coalesce(p_title, ''))) not between 1 and 500 or p_starts_at is null then
        raise exception 'event title and start are required' using errcode = '22023';
    end if;
    insert into public.events (household_id, title, starts_at, ends_at, person, assignee, created_by)
    values (p_household_id, trim(p_title), p_starts_at, p_ends_at, nullif(trim(coalesce(p_person, '')), ''), p_assignee, p_actor_user_id)
    returning * into created_event;
    return to_jsonb(created_event);
end;
$$;

create or replace function public.create_grocery_item(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_name text,
    p_quantity numeric default 1,
    p_unit text default 'each',
    p_category text default 'General'
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    created_item public.grocery_items;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    perform 1 from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if char_length(trim(coalesce(p_name, ''))) not between 1 and 300 or coalesce(p_quantity, 0) <= 0 then
        raise exception 'grocery name and positive quantity are required' using errcode = '22023';
    end if;
    insert into public.grocery_items (household_id, name, quantity, unit, category, created_by)
    values (p_household_id, trim(p_name), coalesce(p_quantity, 1), trim(coalesce(p_unit, 'each')), trim(coalesce(p_category, 'General')), p_actor_user_id)
    returning * into created_item;
    return to_jsonb(created_item);
end;
$$;

revoke all on function public.create_task(uuid, uuid, text, timestamptz, uuid, uuid, boolean, text) from public;
revoke all on function public.create_event(uuid, uuid, text, timestamptz, timestamptz, text, uuid) from public;
revoke all on function public.create_grocery_item(uuid, uuid, text, numeric, text, text) from public;
grant execute on function public.create_task(uuid, uuid, text, timestamptz, uuid, uuid, boolean, text) to authenticated, service_role;
grant execute on function public.create_event(uuid, uuid, text, timestamptz, timestamptz, text, uuid) to authenticated, service_role;
grant execute on function public.create_grocery_item(uuid, uuid, text, numeric, text, text) to authenticated, service_role;

create or replace function public.create_chore_task(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_chore_id uuid,
    p_due_at timestamptz default null
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    chore_row public.chore_templates;
    created_task public.tasks;
    participant_count integer;
    participant_text text;
    participant_id uuid;
    current_index integer;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    perform 1 from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    select * into chore_row
    from public.chore_templates
    where id = p_chore_id and household_id = p_household_id and active
    for update;
    if not found then
        raise exception 'active chore not found' using errcode = 'P0002';
    end if;
    participant_count := jsonb_array_length(coalesce(chore_row.participants, '[]'::jsonb));
    current_index := greatest(coalesce(chore_row.next_index, 0), 0);
    if participant_count > 0 then
        participant_text := nullif(trim(chore_row.participants ->> (current_index % participant_count)), '');
        if participant_text is not null then
            if participant_text !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
                raise exception 'chore participant must be a user id' using errcode = '22023';
            end if;
            participant_id := participant_text::uuid;
        end if;
    end if;
    if participant_id is not null then
        perform 1 from public.memberships
        where household_id = p_household_id and user_id = participant_id
        for update;
        if not found then
            raise exception 'chore participant must be a household member' using errcode = '22023';
        end if;
    end if;
    insert into public.tasks (household_id, title, due_at, assignee, status, created_by)
    values (p_household_id, chore_row.title, p_due_at, participant_id, 'open', p_actor_user_id)
    returning * into created_task;
    update public.chore_templates
    set next_index = current_index + 1
    where id = chore_row.id;
    return to_jsonb(created_task);
end;
$$;

revoke all on function public.create_chore_task(uuid, uuid, uuid, timestamptz) from public;
grant execute on function public.create_chore_task(uuid, uuid, uuid, timestamptz) to authenticated, service_role;

delete from public.channel_identities identity
where (
    select count(*)
    from public.memberships membership
    where membership.user_id = identity.user_id
) > 1;

grant execute on function public.accept_invitation(text, text) to authenticated;

create or replace function public.accept_invitation(raw_token text, display_name text)
returns public.memberships
language plpgsql security definer set search_path = public, extensions as $$
declare
    invitation public.invitations;
    created_membership public.memberships;
    invite_email text := lower(trim(coalesce((select auth.jwt() ->> 'email'), '')));
begin
    if auth.uid() is null then
        raise exception 'authentication required' using errcode = '42501';
    end if;
    select i.* into invitation
    from public.invitations i
    where i.token_hash = encode(digest(raw_token, 'sha256'), 'hex')
      and i.revoked_at is null
      and i.accepted_at is null
      and i.expires_at > timezone('utc', now())
    for update;
    if not found then
        raise exception 'invitation is invalid or expired' using errcode = '22023';
    end if;
    if lower(trim(invitation.email)) <> invite_email then
        raise exception 'invitation email does not match sign-in email' using errcode = '42501';
    end if;
    insert into public.memberships (household_id, user_id, role)
    values (invitation.household_id, auth.uid(), invitation.role)
    on conflict (household_id, user_id) do update
        set role = case
            when public.memberships.role = 'owner' then public.memberships.role
            else excluded.role
        end
    returning * into created_membership;
    update public.invitations
    set accepted_at = timezone('utc', now()), accepted_user_id = auth.uid()
    where id = invitation.id;
    insert into public.profiles (user_id, email, display_name)
    values (
        auth.uid(),
        invite_email,
        coalesce(nullif(trim(display_name), ''), split_part(invite_email, '@', 1))
    )
    on conflict (user_id) do update
        set email = excluded.email,
            display_name = excluded.display_name,
            updated_at = timezone('utc', now());
    return created_membership;
end;
$$;
revoke all on function public.accept_invitation(text, text) from public, anon;
grant execute on function public.accept_invitation(text, text) to authenticated;

create or replace function public.manage_membership(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_member_user_id uuid,
    p_action text,
    p_role text default null
)
returns public.memberships
language plpgsql security definer set search_path = public as $$
declare
    actor_membership public.memberships;
    target_membership public.memberships;
    owner_count integer;
begin
    if auth.uid() is null or p_actor_user_id <> auth.uid() then
        raise exception 'actor mismatch' using errcode = '42501';
    end if;
    if p_action not in ('remove', 'role') then
        raise exception 'invalid membership action' using errcode = '22023';
    end if;
    if p_action = 'role' and p_role not in ('owner', 'member', 'child', 'guest') then
        raise exception 'invalid membership role' using errcode = '22023';
    end if;

    perform 1
    from public.memberships
    where household_id = p_household_id
    order by user_id
    for update;

    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id;
    if not found or actor_membership.role <> 'owner' then
        raise exception 'owner access required' using errcode = '42501';
    end if;

    select * into target_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_member_user_id;
    if not found then
        raise exception 'member not found' using errcode = '22023';
    end if;
    if p_action = 'remove' and p_member_user_id = p_actor_user_id then
        raise exception 'cannot remove yourself' using errcode = '42501';
    end if;

    select count(*) into owner_count
    from public.memberships
    where household_id = p_household_id and role = 'owner';
    if target_membership.role = 'owner'
       and owner_count <= 1
       and (p_action = 'remove' or p_role <> 'owner') then
        raise exception 'household must retain an owner' using errcode = '22023';
    end if;

    if p_action = 'remove' then
        delete from public.memberships
        where household_id = p_household_id and user_id = p_member_user_id;
    else
        update public.memberships
        set role = p_role
        where household_id = p_household_id and user_id = p_member_user_id
        returning * into target_membership;
    end if;
    return target_membership;
end;
$$;
revoke all on function public.manage_membership(uuid, uuid, uuid, text, text) from public;
grant execute on function public.manage_membership(uuid, uuid, uuid, text, text) to authenticated;
revoke insert, update, delete on public.memberships from authenticated;

create or replace function public.delete_task(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_task_id uuid
)
returns public.tasks
language plpgsql security definer set search_path = public as $$
declare
    actor_membership public.memberships;
    task_row public.tasks;
    deleted_task public.tasks;
begin
    if auth.uid() is null or p_actor_user_id <> auth.uid() then
        raise exception 'actor mismatch' using errcode = '42501';
    end if;
    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    select * into task_row
    from public.tasks
    where id = p_task_id and household_id = p_household_id
    for update;
    if not found then
        raise exception 'task not found' using errcode = '22023';
    end if;
    if task_row.private
       and task_row.owner is distinct from p_actor_user_id
       and task_row.created_by is distinct from p_actor_user_id then
        raise exception 'private task access denied' using errcode = '42501';
    end if;
    delete from public.tasks
    where id = task_row.id
    returning * into deleted_task;
    insert into public.activity_log (household_id, actor, action, entity_type, entity_id, before_json)
    values (
        p_household_id,
        p_actor_user_id,
        'task.deleted',
        'task',
        task_row.id,
        jsonb_build_object(
            'id', task_row.id,
            'status', task_row.status,
            'private', task_row.private,
            'owner', task_row.owner,
            'created_by', task_row.created_by
        )
    );
    return deleted_task;
end;
$$;
revoke all on function public.delete_task(uuid, uuid, uuid) from public;
grant execute on function public.delete_task(uuid, uuid, uuid) to authenticated;
revoke delete on public.tasks from authenticated;
