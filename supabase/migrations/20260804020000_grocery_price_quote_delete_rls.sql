drop policy if exists grocery_price_quotes_member_delete on public.grocery_price_quotes;
create policy grocery_price_quotes_member_delete
on public.grocery_price_quotes for delete to authenticated
using (
    private.is_household_member(household_id)
    and exists (
        select 1 from public.grocery_items item
        where item.id = grocery_price_quotes.grocery_item_id
          and item.household_id = grocery_price_quotes.household_id
    )
);
