create table if not exists public.grocery_price_quotes (
    id uuid primary key default gen_random_uuid(),
    household_id uuid not null references public.households(id) on delete cascade,
    grocery_item_id uuid not null references public.grocery_items(id) on delete cascade,
    retailer text not null check (retailer in ('coles', 'aldi', 'woolworths')),
    product_key text not null check (char_length(trim(product_key)) between 1 and 120),
    product_title text not null check (char_length(trim(product_title)) between 1 and 500),
    product_url text not null check (product_url ~ '^https://'),
    price numeric(10,2) not null check (price >= 0),
    observed_at timestamptz not null,
    confidence text not null check (confidence in ('curated', 'live', 'manual')),
    match_basis text not null default 'normalized alias',
    note text not null default '',
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (grocery_item_id, retailer)
);

create index if not exists grocery_price_quotes_household_idx
    on public.grocery_price_quotes(household_id, retailer, updated_at desc);
create index if not exists grocery_price_quotes_item_idx
    on public.grocery_price_quotes(grocery_item_id, retailer);

create or replace function private.prevent_grocery_price_quote_scope_change()
returns trigger language plpgsql set search_path = public as $$
begin
    if new.household_id <> old.household_id
       or new.grocery_item_id <> old.grocery_item_id
       or new.retailer <> old.retailer then
        raise exception 'grocery price quote scope is immutable' using errcode = '42501';
    end if;
    new.updated_at := timezone('utc', now());
    return new;
end;
$$;

drop trigger if exists grocery_price_quotes_scope_guard on public.grocery_price_quotes;
create trigger grocery_price_quotes_scope_guard
before update on public.grocery_price_quotes
for each row execute function private.prevent_grocery_price_quote_scope_change();

alter table public.grocery_price_quotes enable row level security;

drop policy if exists grocery_price_quotes_member_select on public.grocery_price_quotes;
create policy grocery_price_quotes_member_select
on public.grocery_price_quotes for select to authenticated
using (
    private.is_household_member(household_id)
    and exists (
        select 1 from public.grocery_items item
        where item.id = grocery_price_quotes.grocery_item_id
          and item.household_id = grocery_price_quotes.household_id
    )
);

drop policy if exists grocery_price_quotes_member_insert on public.grocery_price_quotes;
create policy grocery_price_quotes_member_insert
on public.grocery_price_quotes for insert to authenticated
with check (
    private.is_household_member(household_id)
    and exists (
        select 1 from public.grocery_items item
        where item.id = grocery_price_quotes.grocery_item_id
          and item.household_id = grocery_price_quotes.household_id
    )
);

drop policy if exists grocery_price_quotes_member_update on public.grocery_price_quotes;
create policy grocery_price_quotes_member_update
on public.grocery_price_quotes for update to authenticated
using (
    private.is_household_member(household_id)
    and exists (
        select 1 from public.grocery_items item
        where item.id = grocery_price_quotes.grocery_item_id
          and item.household_id = grocery_price_quotes.household_id
    )
)
with check (
    private.is_household_member(household_id)
    and exists (
        select 1 from public.grocery_items item
        where item.id = grocery_price_quotes.grocery_item_id
          and item.household_id = grocery_price_quotes.household_id
    )
);

drop policy if exists grocery_price_quotes_member_delete on public.grocery_price_quotes;
create policy grocery_price_quotes_member_delete
on public.grocery_price_quotes for delete to authenticated
using (private.is_household_member(household_id));

grant select, insert, update, delete on public.grocery_price_quotes to authenticated;
