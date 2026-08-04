-- Keep meal creation, edits, and deletion behind membership-checked,
-- auditable transactions.
-- The browser/API supplies a proposed patch; the database owns identity,
-- household membership, cook validation, row locking, and activity history.

-- Existing records created before this migration may contain a cook who was
-- not a member of the meal's household. Clear that invalid assignment before
-- adding the invariant; the household can assign a valid cook again.
update public.meals meal
set cook = null
where meal.cook is not null
  and not exists (
      select 1
      from public.memberships membership
      where membership.household_id = meal.household_id
        and membership.user_id = meal.cook
  );

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.meals'::regclass
          and conname = 'meals_household_cook_membership_fkey'
    ) then
        alter table public.meals
            add constraint meals_household_cook_membership_fkey
            foreign key (household_id, cook)
            references public.memberships (household_id, user_id)
            on delete set null (cook);
    end if;
end;
$$;

create or replace function public.create_meal(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_meal jsonb
)
returns public.meals
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    created_meal public.meals;
    meal_date_value date;
    meal_type_value text;
    title_value text;
    cook_value uuid;
    status_value text;
    ingredients_value jsonb;
begin
    if auth.role() <> 'service_role'
       and (auth.uid() is null or auth.uid() <> p_actor_user_id) then
        raise exception 'actor must match authenticated user' using errcode = '42501';
    end if;
    if p_meal is null or jsonb_typeof(p_meal) <> 'object' then
        raise exception 'meal payload must be an object' using errcode = '22023';
    end if;
    if pg_column_size(p_meal) > 16384 then
        raise exception 'meal payload is too large' using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_object_keys(p_meal) key
        where key not in ('meal_date', 'meal_type', 'title', 'cook', 'status', 'ingredients')
    ) then
        raise exception 'meal payload contains unsupported fields' using errcode = '22023';
    end if;

    if p_meal ? 'cook' and nullif(trim(p_meal->>'cook'), '') is not null then
        begin
            cook_value := (p_meal->>'cook')::uuid;
        exception when invalid_text_representation then
            raise exception 'meal cook is invalid' using errcode = '22023';
        end;
    else
        cook_value := null;
    end if;

    perform 1
    from public.memberships
    where household_id = p_household_id
      and user_id in (p_actor_user_id, cook_value)
    order by user_id
    for update;
    if not exists (
        select 1 from public.memberships
        where household_id = p_household_id and user_id = p_actor_user_id
    ) then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if cook_value is not null and not exists (
        select 1 from public.memberships
        where household_id = p_household_id and user_id = cook_value
    ) then
        raise exception 'meal cook must belong to household' using errcode = '42501';
    end if;

    if nullif(trim(p_meal->>'meal_date'), '') is null then
        raise exception 'meal date is required' using errcode = '22023';
    end if;
    begin
        meal_date_value := (p_meal->>'meal_date')::date;
    exception when invalid_text_representation or datetime_field_overflow then
        raise exception 'meal date is invalid' using errcode = '22023';
    end;

    meal_type_value := lower(trim(coalesce(p_meal->>'meal_type', 'dinner')));
    if meal_type_value not in ('breakfast', 'lunch', 'dinner') then
        raise exception 'meal type is invalid' using errcode = '22023';
    end if;

    title_value := trim(coalesce(p_meal->>'title', ''));
    if char_length(title_value) not between 1 and 500 then
        raise exception 'meal title is required' using errcode = '22023';
    end if;

    status_value := lower(trim(coalesce(p_meal->>'status', 'planned')));
    if status_value not in ('planned', 'served', 'archived') then
        raise exception 'meal status is invalid' using errcode = '22023';
    end if;

    if p_meal ? 'ingredients' then
        if jsonb_typeof(p_meal->'ingredients') <> 'array' then
            raise exception 'meal ingredients are invalid' using errcode = '22023';
        end if;
        if jsonb_array_length(p_meal->'ingredients') > 100 then
            raise exception 'meal ingredients are invalid' using errcode = '22023';
        end if;
        if exists (
            select 1
            from jsonb_array_elements(p_meal->'ingredients') ingredient
            where jsonb_typeof(ingredient) <> 'string'
               or char_length(trim(ingredient #>> '{}')) not between 1 and 200
        ) then
            raise exception 'meal ingredients are invalid' using errcode = '22023';
        end if;
        ingredients_value := p_meal->'ingredients';
    else
        ingredients_value := '[]'::jsonb;
    end if;

    insert into public.meals (
        household_id, meal_date, meal_type, title, cook, status, ingredients, created_by
    ) values (
        p_household_id, meal_date_value, meal_type_value, title_value,
        cook_value, status_value, ingredients_value, p_actor_user_id
    ) returning * into created_meal;

    insert into public.activity_log (
        household_id, actor, action, entity_type, entity_id, after_json
    ) values (
        p_household_id, p_actor_user_id, 'meal.created', 'meal', created_meal.id, to_jsonb(created_meal)
    );

    return created_meal;
end;
$$;

create or replace function public.update_meal(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_meal_id uuid,
    p_patch jsonb
)
returns public.meals
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    meal_row public.meals;
    updated_meal public.meals;
    meal_date_value date;
    meal_type_value text;
    title_value text;
    cook_value uuid;
    status_value text;
    ingredients_value jsonb;
begin
    if auth.role() <> 'service_role'
       and (auth.uid() is null or auth.uid() <> p_actor_user_id) then
        raise exception 'actor must match authenticated user' using errcode = '42501';
    end if;
    if p_patch is null or jsonb_typeof(p_patch) <> 'object' then
        raise exception 'meal patch must be an object' using errcode = '22023';
    end if;
    if not exists (select 1 from jsonb_object_keys(p_patch)) then
        raise exception 'meal patch must not be empty' using errcode = '22023';
    end if;
    if pg_column_size(p_patch) > 16384 then
        raise exception 'meal patch is too large' using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_object_keys(p_patch) key
        where key not in ('meal_date', 'meal_type', 'title', 'cook', 'status', 'ingredients')
    ) then
        raise exception 'meal patch contains unsupported fields' using errcode = '22023';
    end if;

    if p_patch ? 'cook' then
        if nullif(trim(p_patch->>'cook'), '') is null then
            cook_value := null;
        else
            begin
                cook_value := (p_patch->>'cook')::uuid;
            exception when invalid_text_representation then
                raise exception 'meal cook is invalid' using errcode = '22023';
            end;
        end if;
    end if;

    perform 1
    from public.memberships
    where household_id = p_household_id
      and user_id in (p_actor_user_id, cook_value)
    order by user_id
    for update;
    if not exists (
        select 1 from public.memberships
        where household_id = p_household_id and user_id = p_actor_user_id
    ) then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if p_patch ? 'cook' and cook_value is not null and not exists (
        select 1 from public.memberships
        where household_id = p_household_id and user_id = cook_value
    ) then
        raise exception 'meal cook must belong to household' using errcode = '42501';
    end if;

    select * into meal_row
    from public.meals
    where id = p_meal_id and household_id = p_household_id
    for update;
    if not found then
        raise exception 'meal not found' using errcode = 'P0002';
    end if;

    if p_patch ? 'meal_date' then
        if nullif(trim(p_patch->>'meal_date'), '') is null then
            raise exception 'meal date is required' using errcode = '22023';
        end if;
        begin
            meal_date_value := (p_patch->>'meal_date')::date;
        exception when invalid_text_representation or datetime_field_overflow then
            raise exception 'meal date is invalid' using errcode = '22023';
        end;
    else
        meal_date_value := meal_row.meal_date;
    end if;

    if p_patch ? 'meal_type' then
        meal_type_value := lower(trim(coalesce(p_patch->>'meal_type', '')));
        if meal_type_value not in ('breakfast', 'lunch', 'dinner') then
            raise exception 'meal type is invalid' using errcode = '22023';
        end if;
    else
        meal_type_value := meal_row.meal_type;
    end if;

    if p_patch ? 'title' then
        title_value := trim(coalesce(p_patch->>'title', ''));
        if char_length(title_value) not between 1 and 500 then
            raise exception 'meal title is required' using errcode = '22023';
        end if;
    else
        title_value := meal_row.title;
    end if;

    if not p_patch ? 'cook' then
        cook_value := meal_row.cook;
    end if;

    if p_patch ? 'status' then
        status_value := lower(trim(coalesce(p_patch->>'status', '')));
        if status_value not in ('planned', 'served', 'archived') then
            raise exception 'meal status is invalid' using errcode = '22023';
        end if;
    else
        status_value := meal_row.status;
    end if;

    if p_patch ? 'ingredients' then
        if jsonb_typeof(p_patch->'ingredients') <> 'array' then
            raise exception 'meal ingredients are invalid' using errcode = '22023';
        end if;
        if jsonb_array_length(p_patch->'ingredients') > 100 then
            raise exception 'meal ingredients are invalid' using errcode = '22023';
        end if;
        if exists (
            select 1
            from jsonb_array_elements(p_patch->'ingredients') ingredient
            where jsonb_typeof(ingredient) <> 'string'
               or char_length(trim(ingredient #>> '{}')) not between 1 and 200
        ) then
            raise exception 'meal ingredients are invalid' using errcode = '22023';
        end if;
        ingredients_value := p_patch->'ingredients';
    else
        ingredients_value := meal_row.ingredients;
    end if;

    update public.meals
    set meal_date = meal_date_value,
        meal_type = meal_type_value,
        title = title_value,
        cook = cook_value,
        status = status_value,
        ingredients = ingredients_value
    where id = p_meal_id and household_id = p_household_id
    returning * into updated_meal;

    insert into public.activity_log (
        household_id, actor, action, entity_type, entity_id, before_json, after_json
    ) values (
        p_household_id,
        p_actor_user_id,
        'meal.updated',
        'meal',
        p_meal_id,
        to_jsonb(meal_row),
        to_jsonb(updated_meal)
    );

    return updated_meal;
end;
$$;

create or replace function public.delete_meal(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_meal_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    actor_membership public.memberships;
    meal_row public.meals;
    deleted_meal public.meals;
begin
    if auth.role() <> 'service_role'
       and (auth.uid() is null or auth.uid() <> p_actor_user_id) then
        raise exception 'actor must match authenticated user' using errcode = '42501';
    end if;

    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;

    select * into meal_row
    from public.meals
    where id = p_meal_id and household_id = p_household_id
    for update;
    if not found then
        raise exception 'meal not found' using errcode = 'P0002';
    end if;

    delete from public.meals
    where id = p_meal_id and household_id = p_household_id
    returning * into deleted_meal;

    insert into public.activity_log (
        household_id, actor, action, entity_type, entity_id, before_json
    ) values (
        p_household_id,
        p_actor_user_id,
        'meal.deleted',
        'meal',
        p_meal_id,
        to_jsonb(meal_row)
    );

    return jsonb_build_object('deleted', true, 'id', deleted_meal.id);
end;
$$;

revoke all on function public.create_meal(uuid, uuid, jsonb) from public, anon, authenticated, service_role;
revoke all on function public.update_meal(uuid, uuid, uuid, jsonb) from public, anon, authenticated, service_role;
revoke all on function public.delete_meal(uuid, uuid, uuid) from public, anon, authenticated, service_role;
grant execute on function public.create_meal(uuid, uuid, jsonb) to authenticated, service_role;
grant execute on function public.update_meal(uuid, uuid, uuid, jsonb) to authenticated, service_role;
grant execute on function public.delete_meal(uuid, uuid, uuid) to authenticated, service_role;

-- PostgREST meal mutations must use the functions above so direct clients
-- cannot skip cook membership validation or the activity records.
revoke insert, update, delete on public.meals from authenticated;
revoke insert, update, delete on public.activity_log from authenticated;

create policy memberships_delete_owner on public.memberships
for delete to authenticated
using (private.is_household_owner(household_id) and user_id <> (select auth.uid()));
