begin;

alter table public.chore_templates
    add column if not exists next_due_at timestamptz;

create index if not exists chore_templates_household_due_idx
    on public.chore_templates(household_id, next_due_at)
    where active;

create or replace function public.create_chore_template(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_title text,
    p_cadence text,
    p_participants jsonb,
    p_next_due_at timestamptz default null
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    created_chore public.chore_templates;
    participant_text text;
    participant_id uuid;
    participant_count integer;
    normalized_participants jsonb := '[]'::jsonb;
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
    if char_length(trim(coalesce(p_title, ''))) not between 1 and 300 then
        raise exception 'chore title is required' using errcode = '22023';
    end if;
    if lower(trim(coalesce(p_cadence, ''))) not in ('daily', 'weekly', 'fortnightly', 'monthly', 'yearly', 'on_demand') then
        raise exception 'invalid chore cadence' using errcode = '22023';
    end if;
    if p_participants is null or jsonb_typeof(p_participants) <> 'array' then
        raise exception 'chore participants must be an array' using errcode = '22023';
    end if;
    participant_count := jsonb_array_length(p_participants);
    if participant_count < 1 or participant_count > 20 then
        raise exception 'chore participants must contain between 1 and 20 members' using errcode = '22023';
    end if;
    for participant_text in select jsonb_array_elements_text(p_participants) loop
        if participant_text is null or participant_text !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
            raise exception 'chore participant must be a user id' using errcode = '22023';
        end if;
        participant_id := participant_text::uuid;
        perform 1 from public.memberships
        where household_id = p_household_id and user_id = participant_id;
        if not found then
            raise exception 'chore participant must be a household member' using errcode = '22023';
        end if;
        if not (normalized_participants ? (participant_id::text)) then
            normalized_participants := normalized_participants || to_jsonb(participant_id::text);
        end if;
    end loop;
    insert into public.chore_templates (household_id, title, cadence, participants, next_due_at, created_by)
    values (p_household_id, trim(p_title), lower(trim(p_cadence)), normalized_participants, p_next_due_at, p_actor_user_id)
    returning * into created_chore;
    insert into public.activity_log (household_id, actor, action, entity_type, entity_id, after_json)
    values (
        p_household_id,
        p_actor_user_id,
        'chore.created',
        'chore',
        created_chore.id,
        jsonb_build_object(
            'id', created_chore.id,
            'cadence', created_chore.cadence,
            'participant_count', jsonb_array_length(normalized_participants),
            'next_due_at', created_chore.next_due_at
        )
    );
    return to_jsonb(created_chore);
end;
$$;

revoke all on function public.create_chore_template(uuid, uuid, text, text, jsonb, timestamptz) from public;
grant execute on function public.create_chore_template(uuid, uuid, text, text, jsonb, timestamptz) to authenticated, service_role;

create or replace function public.update_chore_template(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_chore_id uuid,
    p_title text,
    p_cadence text,
    p_participants jsonb,
    p_next_due_at timestamptz default null
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    existing_chore public.chore_templates;
    updated_chore public.chore_templates;
    participant_text text;
    participant_id uuid;
    participant_count integer;
    normalized_participants jsonb := '[]'::jsonb;
    locked_user_id uuid;
    actor_member_found boolean := false;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    select * into existing_chore from public.chore_templates
    where id = p_chore_id and household_id = p_household_id and active
    for update;
    if not found then
        raise exception 'active chore not found' using errcode = 'P0002';
    end if;
    if char_length(trim(coalesce(p_title, ''))) not between 1 and 300 then
        raise exception 'chore title is required' using errcode = '22023';
    end if;
    if lower(trim(coalesce(p_cadence, ''))) not in ('daily', 'weekly', 'fortnightly', 'monthly', 'yearly', 'on_demand') then
        raise exception 'invalid chore cadence' using errcode = '22023';
    end if;
    if p_participants is null or jsonb_typeof(p_participants) <> 'array' then
        raise exception 'chore participants must be an array' using errcode = '22023';
    end if;
    participant_count := jsonb_array_length(p_participants);
    if participant_count < 1 or participant_count > 20 then
        raise exception 'chore participants must contain between 1 and 20 members' using errcode = '22023';
    end if;
    for participant_text in select jsonb_array_elements_text(p_participants) loop
        if participant_text is null or participant_text !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
            raise exception 'chore participant must be a user id' using errcode = '22023';
        end if;
        participant_id := participant_text::uuid;
        if not (normalized_participants ? (participant_id::text)) then
            normalized_participants := normalized_participants || to_jsonb(participant_id::text);
        end if;
    end loop;
    for locked_user_id in
        select user_id from public.memberships
        where household_id = p_household_id
          and (user_id = p_actor_user_id or user_id in (
              select value::uuid from jsonb_array_elements_text(normalized_participants) as participant(value)
          ))
        order by user_id
        for update
    loop
        if locked_user_id = p_actor_user_id then actor_member_found := true; end if;
    end loop;
    if not actor_member_found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if exists (
        select 1
        from jsonb_array_elements_text(normalized_participants) as participant(value)
        where not exists (
            select 1 from public.memberships
            where household_id = p_household_id and user_id = participant.value::uuid
        )
    ) then
        raise exception 'chore participant must be a household member' using errcode = '22023';
    end if;
    update public.chore_templates
    set title = trim(p_title), cadence = lower(trim(p_cadence)), participants = normalized_participants, next_due_at = p_next_due_at
    where id = p_chore_id and household_id = p_household_id and active
    returning * into updated_chore;
    insert into public.activity_log (household_id, actor, action, entity_type, entity_id, before_json, after_json)
    values (
        p_household_id,
        p_actor_user_id,
        'chore.updated',
        'chore',
        p_chore_id,
        jsonb_build_object('id', existing_chore.id, 'cadence', existing_chore.cadence, 'participant_count', jsonb_array_length(existing_chore.participants), 'next_due_at', existing_chore.next_due_at),
        jsonb_build_object('id', updated_chore.id, 'cadence', updated_chore.cadence, 'participant_count', jsonb_array_length(updated_chore.participants), 'next_due_at', updated_chore.next_due_at)
    );
    return to_jsonb(updated_chore);
end;
$$;

revoke all on function public.update_chore_template(uuid, uuid, uuid, text, text, jsonb, timestamptz) from public;
grant execute on function public.update_chore_template(uuid, uuid, uuid, text, text, jsonb, timestamptz) to authenticated, service_role;

revoke insert, update, delete on public.chore_templates from authenticated;
grant select on public.chore_templates to authenticated;

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
    updated_chore public.chore_templates;
    participant_count integer;
    participant_text text;
    participant_id uuid;
    current_index integer;
    scheduled_due_at timestamptz;
    next_schedule_at timestamptz;
    locked_user_id uuid;
    actor_member_found boolean := false;
    participant_member_found boolean := false;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;

    select * into chore_row
    from public.chore_templates
    where id = p_chore_id and household_id = p_household_id and active
    for update;
    if not found then
        raise exception 'active chore not found' using errcode = 'P0002';
    end if;

    participant_count := jsonb_array_length(coalesce(chore_row.participants, '[]'::jsonb));
    if participant_count < 1 then
        raise exception 'chore has no eligible participants' using errcode = '22023';
    end if;
    current_index := greatest(coalesce(chore_row.next_index, 0), 0);
    if participant_count > 0 then
        participant_text := nullif(trim(chore_row.participants ->> (current_index % participant_count)), '');
        if participant_text is not null then
            if participant_text is null or participant_text !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
                raise exception 'chore participant must be a user id' using errcode = '22023';
            end if;
            participant_id := participant_text::uuid;
        end if;
    end if;

    for locked_user_id in
        select user_id from public.memberships
        where household_id = p_household_id
          and user_id in (p_actor_user_id, participant_id)
        order by user_id
        for update
    loop
        if locked_user_id = p_actor_user_id then actor_member_found := true; end if;
        if participant_id is not null and locked_user_id = participant_id then participant_member_found := true; end if;
    end loop;
    if not actor_member_found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if participant_id is not null and not participant_member_found then
        raise exception 'chore participant must be a household member' using errcode = '22023';
    end if;

    scheduled_due_at := coalesce(p_due_at, chore_row.next_due_at);
    next_schedule_at := null;
    if chore_row.next_due_at is not null then
        case lower(trim(coalesce(chore_row.cadence, '')))
            when 'daily' then next_schedule_at := chore_row.next_due_at + interval '1 day';
            when 'weekly' then next_schedule_at := chore_row.next_due_at + interval '1 week';
            when 'fortnightly' then next_schedule_at := chore_row.next_due_at + interval '2 weeks';
            when 'monthly' then next_schedule_at := chore_row.next_due_at + interval '1 month';
            when 'yearly' then next_schedule_at := chore_row.next_due_at + interval '1 year';
            else next_schedule_at := null;
        end case;
    end if;

    insert into public.tasks (household_id, title, due_at, assignee, status, created_by)
    values (p_household_id, chore_row.title, scheduled_due_at, participant_id, 'open', p_actor_user_id)
    returning * into created_task;

    update public.chore_templates
    set next_index = current_index + 1,
        next_due_at = next_schedule_at
    where id = chore_row.id
    returning * into updated_chore;

    insert into public.activity_log (household_id, actor, action, entity_type, entity_id, after_json)
    values (
        p_household_id,
        p_actor_user_id,
        'chore.assigned',
        'chore',
        chore_row.id,
        jsonb_build_object(
            'chore_id', chore_row.id,
            'task_id', created_task.id,
            'assignee', participant_id,
            'due_at', scheduled_due_at,
            'next_index', current_index + 1
        )
    );

    return jsonb_build_object('task', to_jsonb(created_task), 'chore', to_jsonb(updated_chore));
end;
$$;

revoke all on function public.create_chore_task(uuid, uuid, uuid, timestamptz) from public;
grant execute on function public.create_chore_task(uuid, uuid, uuid, timestamptz) to authenticated, service_role;

commit;
