create schema if not exists private;
revoke all on schema private from public;

drop policy if exists households_select_member on public.households;
drop policy if exists households_update_owner on public.households;
drop policy if exists households_delete_owner on public.households;
drop policy if exists memberships_select_member on public.memberships;
drop policy if exists memberships_update_owner on public.memberships;
drop policy if exists inbox_items_member_select on public.inbox_items;
drop policy if exists inbox_items_member_insert on public.inbox_items;
drop policy if exists inbox_items_member_update on public.inbox_items;
drop policy if exists inbox_items_member_delete on public.inbox_items;
drop policy if exists tasks_member_select on public.tasks;
drop policy if exists tasks_member_insert on public.tasks;
drop policy if exists tasks_member_update on public.tasks;
drop policy if exists tasks_member_delete on public.tasks;
drop policy if exists events_member_select on public.events;
drop policy if exists events_member_insert on public.events;
drop policy if exists events_member_update on public.events;
drop policy if exists events_member_delete on public.events;
drop policy if exists meals_member_select on public.meals;
drop policy if exists meals_member_insert on public.meals;
drop policy if exists meals_member_update on public.meals;
drop policy if exists meals_member_delete on public.meals;
drop policy if exists grocery_items_member_select on public.grocery_items;
drop policy if exists grocery_items_member_insert on public.grocery_items;
drop policy if exists grocery_items_member_update on public.grocery_items;
drop policy if exists grocery_items_member_delete on public.grocery_items;
drop policy if exists activity_log_member_select on public.activity_log;
drop policy if exists activity_log_member_insert on public.activity_log;
drop function if exists public.is_household_member(uuid);
drop function if exists public.is_household_owner(uuid);

create or replace function private.is_household_member(target_household_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
    select exists (select 1 from public.memberships where household_id = target_household_id and user_id = (select auth.uid()));
$$;

create or replace function private.is_household_owner(target_household_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
    select exists (select 1 from public.memberships where household_id = target_household_id and user_id = (select auth.uid()) and role = 'owner');
$$;

revoke all on function private.is_household_member(uuid) from public;
revoke all on function private.is_household_owner(uuid) from public;
grant execute on function private.is_household_member(uuid) to authenticated;
grant execute on function private.is_household_owner(uuid) to authenticated;

create or replace function private.create_household(household_name text)
returns public.households language plpgsql security definer set search_path = public as $$
declare created_household public.households;
begin
    if auth.uid() is null then raise exception 'authentication required' using errcode = '42501'; end if;
    if char_length(trim(coalesce(household_name, ''))) not between 1 and 120 then
        raise exception 'household name is required' using errcode = '22023';
    end if;
    insert into public.households (name, created_by) values (trim(household_name), auth.uid()) returning * into created_household;
    insert into public.memberships (household_id, user_id, role) values (created_household.id, auth.uid(), 'owner');
    return created_household;
end;
$$;

revoke all on function private.create_household(text) from public;
grant execute on function private.create_household(text) to authenticated;

create or replace function public.create_household(household_name text)
returns public.households language sql security invoker set search_path = public, private as $$
    select * from private.create_household($1);
$$;

revoke all on function public.create_household(text) from public;
grant execute on function public.create_household(text) to authenticated;

create policy households_select_member on public.households for select to authenticated using (private.is_household_member(id));
create policy households_update_owner on public.households for update to authenticated using (private.is_household_owner(id)) with check (private.is_household_owner(id));
create policy households_delete_owner on public.households for delete to authenticated using (private.is_household_owner(id));

create policy memberships_select_member on public.memberships for select to authenticated using (user_id = (select auth.uid()) or private.is_household_member(household_id));
create policy memberships_update_owner on public.memberships for update to authenticated using (private.is_household_owner(household_id)) with check (private.is_household_owner(household_id));

create policy inbox_items_member_select on public.inbox_items for select to authenticated using (private.is_household_member(household_id) and (not private or created_by = (select auth.uid())));
create policy inbox_items_member_insert on public.inbox_items for insert to authenticated with check (private.is_household_member(household_id) and created_by = (select auth.uid()));
create policy inbox_items_member_update on public.inbox_items for update to authenticated using (private.is_household_member(household_id) and (not private or created_by = (select auth.uid()))) with check (private.is_household_member(household_id) and (not private or created_by = (select auth.uid())));
create policy inbox_items_member_delete on public.inbox_items for delete to authenticated using (private.is_household_member(household_id) and (created_by = (select auth.uid()) or private.is_household_owner(household_id)));

create policy tasks_member_select on public.tasks for select to authenticated using (private.is_household_member(household_id) and (not private or owner = (select auth.uid()) or created_by = (select auth.uid())));
create policy tasks_member_insert on public.tasks for insert to authenticated with check (private.is_household_member(household_id) and created_by = (select auth.uid()));
create policy tasks_member_update on public.tasks for update to authenticated using (private.is_household_member(household_id) and (not private or owner = (select auth.uid()) or created_by = (select auth.uid()))) with check (private.is_household_member(household_id) and (not private or owner = (select auth.uid()) or created_by = (select auth.uid())));
create policy tasks_member_delete on public.tasks for delete to authenticated using (private.is_household_member(household_id) and (created_by = (select auth.uid()) or private.is_household_owner(household_id)));

create policy events_member_select on public.events for select to authenticated using (private.is_household_member(household_id));
create policy events_member_insert on public.events for insert to authenticated with check (private.is_household_member(household_id) and created_by = (select auth.uid()));
create policy events_member_update on public.events for update to authenticated using (private.is_household_member(household_id)) with check (private.is_household_member(household_id));
create policy events_member_delete on public.events for delete to authenticated using (private.is_household_member(household_id));

create policy meals_member_select on public.meals for select to authenticated using (private.is_household_member(household_id));
create policy meals_member_insert on public.meals for insert to authenticated with check (private.is_household_member(household_id) and created_by = (select auth.uid()));
create policy meals_member_update on public.meals for update to authenticated using (private.is_household_member(household_id)) with check (private.is_household_member(household_id));
create policy meals_member_delete on public.meals for delete to authenticated using (private.is_household_member(household_id));

create policy grocery_items_member_select on public.grocery_items for select to authenticated using (private.is_household_member(household_id));
create policy grocery_items_member_insert on public.grocery_items for insert to authenticated with check (private.is_household_member(household_id) and created_by = (select auth.uid()));
create policy grocery_items_member_update on public.grocery_items for update to authenticated using (private.is_household_member(household_id)) with check (private.is_household_member(household_id));
create policy grocery_items_member_delete on public.grocery_items for delete to authenticated using (private.is_household_member(household_id));

create policy activity_log_member_select on public.activity_log for select to authenticated using (private.is_household_member(household_id));
create policy activity_log_member_insert on public.activity_log for insert to authenticated with check (private.is_household_member(household_id) and actor = (select auth.uid()));
