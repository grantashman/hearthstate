# Pilot instrumentation and retention

This is a first-party measurement ledger for the hosted household pilot. It exists to answer product decisions about activation, household value, and retention. It is **not** an advertising profile and must not contain household content.

## Privacy boundary

- `pilot_events` stores household/member/record UUIDs, event names, server timestamps, a dedupe key, and a small allowlisted metadata object.
- It never stores inbox text, task titles, event titles, email addresses, URLs, message bodies, invitation bearer tokens, or channel payloads.
- Writes go through the `service_role`-only `record_pilot_event` RPC. The RPC locks and checks the actor's household membership before inserting and applies the same event-specific metadata allowlist as the API.
- Authenticated users have no direct read or write policy for the ledger. Owners can receive the metadata-only facts as part of their normal household export.
- Instrumentation failures are deliberately non-blocking: a household mutation must not become a 5xx because measurement is unavailable.

## Event contract

| Event | Emitted by | Allowed metadata | Product question / decision |
| --- | --- | --- | --- |
| `household_created` | Hosted household setup | `source` | Can a new household finish setup? |
| `member_invited` | Owner invitation creation | `role` | Do households reach the second-member activation step? |
| `member_active` | Authenticated dashboard open, once per member/day | `source` | Is the household used by more than one person? |
| `dashboard_opened` | Authenticated dashboard open, once per member/day | `source` | Are pilot households returning? |
| `capture_created` | Inbox capture creation | `source`, `private` | Is the low-friction capture path used? |
| `capture_converted` | Inbox conversion | `conversion_type` | Does capture become shared value? |
| `task_completed` | Task completion | `source` | Are converted chores/actions completed? |
| `briefing_opened` | Briefing client signal | `source` | Do delivered briefings get opened? |
| `briefing_acted_on` | Briefing client signal | `source`, `action` | Do briefings lead to a useful action? |
| `conflict_resolved` | Conflict-resolution client signal | `source`, `resolution` | Does the product reduce coordination friction? |
| `subscription_started` | Future billing integration | `plan` | Is there willingness to pay? |
| `subscription_cancelled` | Future billing integration | `plan` | What retention/packaging problem needs attention? |
| `subscription_renewed` | Future billing integration | `plan` | Is recurring value durable? |

The current API exposes `POST /api/pilot/events` only for `briefing_opened`, `briefing_acted_on`, and `conflict_resolved`. It requires an authenticated household member and does not accept client-supplied record identifiers; arbitrary event names, entity IDs, and metadata are rejected or discarded. This endpoint is ready for the briefing/resolution UI and does not fabricate events before those surfaces exist.

## Retention queries

Run these queries only from the privileged Supabase SQL editor or an equivalent operational connection. Export aggregate results, not the raw ledger.

### Weekly active households

```sql
select
  date_trunc('week', occurred_at at time zone 'UTC')::date as week_start,
  count(distinct household_id) as active_households
from public.pilot_events
where event_name in ('member_active', 'dashboard_opened', 'capture_created', 'task_completed')
group by 1
order by 1;
```

### Activation funnel

```sql
with household_starts as (
  select household_id, min(occurred_at) as started_at
  from public.pilot_events
  where event_name = 'household_created'
  group by household_id
), milestones as (
  select
    s.household_id,
    bool_or(p.event_name = 'member_invited') as invited,
    count(distinct m.user_id) >= 2 as second_member_active,
    bool_or(p.event_name = 'capture_created') as captured,
    bool_or(p.event_name = 'capture_converted') as converted
  from household_starts s
  left join public.pilot_events p
    on p.household_id = s.household_id
   and p.occurred_at >= s.started_at
  left join public.memberships m on m.household_id = s.household_id
  group by s.household_id
)
select
  count(*) as households_started,
  count(*) filter (where invited) as households_with_invite,
  count(*) filter (where second_member_active) as households_with_second_member,
  count(*) filter (where captured) as households_with_capture,
  count(*) filter (where converted) as households_with_conversion
from milestones;
```

This uses the current membership roster as a conservative second-member proxy. Keep it separate from billing decisions until historical membership activation is available.

### Cohort week-1 retention

```sql
with first_active as (
  select
    household_id,
    min((occurred_at at time zone 'UTC')::date) as first_active_day
  from public.pilot_events
  where event_name in ('member_active', 'dashboard_opened')
  group by household_id
), retained as (
  select distinct
    f.household_id,
    f.first_active_day
  from first_active f
  join public.pilot_events p
    on p.household_id = f.household_id
   and p.event_name in ('member_active', 'dashboard_opened')
   and (p.occurred_at at time zone 'UTC')::date between f.first_active_day + 7 and f.first_active_day + 13
)
select
  date_trunc('week', first_active_day)::date as cohort_week,
  count(*) as activated_households,
  count(r.household_id) as week_1_retained_households,
  round(count(r.household_id)::numeric / nullif(count(*), 0), 3) as week_1_retention
from first_active f
left join retained r using (household_id, first_active_day)
group by 1
order by 1;
```

## Pilot review cadence

- **Weekly:** review activation, weekly active households, capture-to-conversion, and week-1 retention.
- **Decision owner:** product owner decides whether to simplify onboarding, improve briefing usefulness, or proceed to pricing tests.
- **Engineering owner:** confirms event health, dedupe behavior, and migration/RLS integrity.
- **Stop condition:** if an event begins requiring raw household content, do not expand the ledger; redesign the signal as an aggregate or an explicit user action first.
