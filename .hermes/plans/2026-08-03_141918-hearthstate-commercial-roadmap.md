# Hearthstate Commercial Strategy and Development Roadmap

> **Purpose:** Preserve the product decision, market research, pricing hypothesis, and implementation sequence so future sessions can resume without reconstructing the discussion.
>
> **Current status:** P1.1 and P1.2 are implemented on the active feature branch: account/household isolation, owner invitations, one-time invitation acceptance, one-time sign-in tokens, and account-backed dashboard sessions are covered by the test suite. Email/SMS delivery and hosted provisioning remain before a commercial pilot.

## Executive decision

Hearthstate is worth validating as a commercial product, but it should not position itself as another family calendar.

**Working position:**

> Hearthstate helps a household notice what matters, decide who owns it, and get it done without making home feel like a workplace.

The product wedge is the combination of:

- Natural-language capture from the way households already communicate.
- A calm “What needs attention?” operating picture.
- Mental-load reduction through ownership, reminders, conflicts, and briefings.
- Reversible mutations and visible activity history.
- Privacy-aware separation between personal and shared household information.
- Household-wide pricing rather than per-person pricing.

## What exists today

The repository contains a working local vertical slice:

- SQLite-backed planner and dashboard.
- Tailnet-served web app.
- Household chooser for Grant, Billie, and Skye.
- Tasks, assignments, recurrence, calendar, meals, recipes, groceries, budget, and Inbox capture.
- Photon/iMessage planner boundary.
- Activity history with before/after state, archive semantics, and undo.
- Natural-language completion, assignment, renaming, event movement, grocery removal, recent-change queries, and conflict queries.
- Round-robin chores.
- Morning briefing composition with quiet hours and daily deduplication.
- Calendar/task conflict detection.
- Dashboard signals for conflicts, recent activity, and chore rotation.
- CI on Python 3.11 and 3.12.
- 77 automated tests passing at the last release.

The current deployment is not yet a commercial SaaS product. It is a single-household, local SQLite application bound to the Tailscale interface. It lacks hosted multi-tenancy, account invitations, external calendar sync, commercial billing, native push infrastructure, and a public onboarding path.

## Market and competitor notes

The category has proven demand, but the basic feature set is crowded.

| Product | Positioning | Observed pricing | Hearthstate implication |
|---|---|---:|---|
| Cozi | Established family organizer | Free; Gold $39/year; Max $79/year | Large incumbent. Its AI tier validates demand for automation, but its manual workflow leaves room for a calmer conversational product. |
| FamilyWall | Broad all-in-one family hub | $4.99/month or $44.99/year on official pricing page | Strong breadth. Reviews mention notification volume, complexity, and occasional reliability problems. |
| Maple | Modern family assistant and mental-load product | Previously about $3–5/month | Closest strategic comparison. Maple is scheduled to sunset on December 31, 2026 after acquisition by Wander, creating both an acquisition opportunity and a warning about retention economics. |
| OurCal | Privacy-first shared calendar | Subscription product | Validates privacy as a differentiator. It is primarily calendar/chat rather than full household operations. |
| S'moresUp, Nipto, OurHome | Chores, rewards, and allowances | Freemium/subscription | Chore and responsibility products are a separate competitive cluster. Hearthstate should serve adults and whole-household coordination without depending on gamification. |
| Skylight Calendar | Dedicated wall display | Hardware around $280–330 plus $79/year Plus | Competes for the always-visible household hub. Hearthstate can work on devices families already own. |
| Hearth Display | Premium hardware plus membership | About $699 hardware plus $9/month or $86.40/year | Shows that families will pay for household coordination, but Hearthstate should stay software-first and lower-friction. |

### Market conclusion

Do not compete on “calendar + lists + recipes.” Compete on the assistant loop:

1. Capture a messy thought.
2. Understand whether it is a task, event, meal, grocery item, or unresolved Inbox item.
3. Assign ownership and timing.
4. Surface conflicts and due-soon work.
5. Brief the household at the right time.
6. Make changes safe and reversible.

## Commercial model hypothesis

### Recommended launch pricing

**Free**

- One household.
- Up to four members.
- Core calendar, tasks, groceries, and basic meal planning.
- Basic dashboard and limited history.
- No advertising.

**Hearthstate Plus: US$6.99/month or US$59.99/year**

- Unlimited household members and history.
- Proactive briefings and push notifications.
- Calendar conflict detection.
- Chore rotation.
- Conversational, voice, photo, and email capture.
- External calendar integrations.
- Grocery and meal automation.
- Activity history and undo.
- Priority support.

**Founding pilot:** US$49/year for the first 100 households. This is a validation price, not a promised permanent price.

Do not charge per household member. The product needs every member to participate, and per-person pricing creates adoption friction.

### Economics to test

At $59.99/year, a 15% Apple Small Business Program commission would leave approximately $50.99 before taxes and operating costs. At 1,000 annual subscribers, that is approximately $59,990 gross or $50,992 after a 15% store commission.

These numbers are directional. They exclude tax, payment fees, AI usage, storage, notification delivery, support, and refunds.

## Mobile decision

A commercial Hearthstate needs a mobile experience because household coordination happens in short moments: shopping, school pickup, reading an email, remembering something, and responding to a notification.

Do not begin with a full native rewrite.

### Sequence

1. Make the web app mobile-first and installable as a PWA.
2. Build hosted identity and sync behind a stable API.
3. Run a paid pilot and measure repeated capture and retention.
4. Build an iOS companion focused on capture, Today, groceries, task completion, notifications, widgets, Share Sheet, and Siri Shortcuts.
5. Add Android once the interaction model has evidence behind it.

The first iOS app should be a fast companion, not a copy of every dashboard page. Apple widgets and restrained notifications are especially relevant to Hearthstate's “What needs attention?” workflow.

## Product principles

1. **Calm over density.** The product reduces cognitive load instead of becoming another management surface.
2. **Shared by default, private when intended.** A personal reminder must not leak into shared household state.
3. **Every mutation is recoverable.** Archive, activity history, and undo matter more than destructive speed.
4. **Human confirmation for ambiguity.** Suggested conversions should not silently create multiple records.
5. **Household-level pricing.** Everyone should be able to participate.
6. **No advertising or behavioral resale.** Privacy is part of the product promise.
7. **Do not automate noise.** Briefings and notifications need quiet hours, deduplication, and user controls.
8. **Earn the native app.** Build mobile after the capture and sync model proves useful.

# Development roadmap

## Roadmap order

The implementation sequence is:

1. Commercial foundation.
2. Reliable assistant loop.
3. Integrations and data portability.
4. Mobile companion.
5. Paid pilot and retention iteration.
6. Broader automation and Android.

The next coding session should start with **Phase 1, task P1.1: define the hosted household/account boundary**.

---

## Phase 0: Product validation setup

**Goal:** Make the product hypothesis measurable before adding expensive infrastructure.

### P0.1 Define pilot events

**Track:**

- Household created.
- Second member invited and active.
- Capture created.
- Capture converted.
- Task completed.
- Briefing opened or acted on.
- Conflict resolved.
- Weekly active household.
- Subscription started, cancelled, or renewed.

**Done when:** Event names and payloads exist in a short analytics contract and every metric has an owner and a decision it informs.

### P0.2 Write the pilot interview script

Interview questions should test:

- What currently carries household coordination?
- Which information gets lost?
- Who performs the invisible planning work?
- What makes a reminder helpful versus annoying?
- Which records must remain private?
- What would make the household pay $49/year?

**Done when:** The script can be used with 20 pilot households without inventing questions during the interview.

### P0.3 Recruit the first 20 pilot households

Target couples and families with recurring scheduling, school, meal, grocery, or chore coordination. Include at least some ADHD-friendly households and some mixed-device households.

**Done when:** 20 households have agreed to an eight-week pilot, with at least one primary and one invited participant per household.

---

## Phase 1: Commercial foundation

**Goal:** Move from one local household database to a safe hosted product boundary.

### P1.1 Define account, household, and membership models

**Likely files:**

- `hearthstate/store.py`
- New migration module under `hearthstate/`
- New tests under `tests/`
- New API contract document under `docs/` or this plan's implementation notes

**Models:**

- User account.
- Household.
- Household membership.
- Role: owner, member, child/limited member, guest.
- Personal versus shared record scope.

**Done when:** A record cannot be read or mutated outside the active household and membership role, with tests for cross-household access.

**Status:** Complete in P1.1. `HouseholdDirectory` and named `PlannerStore` contexts establish the account/membership and planner isolation seam.

### P1.2 Add invitation and sign-in flow

Use email magic links or an equivalent low-friction authentication method. Keep the existing passwordless household chooser only as a local-development convenience; do not use it as the commercial security model.

**Done when:** A household owner can invite a second member, the invitee can join, and both can see shared records without seeing private records they do not own.

**Status:** Complete for the local account-backed dashboard seam. Invitation and sign-in tokens are hashed, single-use, expiry-enforced at the SQLite claim, and bound to the active household; invitation acceptance is transactional, and API sessions revalidate household membership. The dashboard exposes a `sign_in_delivery` callback boundary for email/SMS integration before hosted pilot use.

### P1.3 Introduce a hosted API boundary

Keep the planner logic separate from transport. The current `Hearthstate` application boundary should remain usable in tests and from Photon while the hosted API becomes the commercial transport.

**Done when:** Web clients do not access SQLite directly, API requests carry authenticated household context, and the local test suite still exercises the application boundary.

### P1.4 Add data export and deletion

Export household records and activity history in a documented JSON format. Add deletion that requires explicit owner confirmation and preserves no recoverable personal data after the retention window.

**Done when:** A test creates a household, exports it, deletes it, and confirms the account cannot read the deleted records.

### P1.5 Add notification preferences and consent state

Store:

- Quiet hours.
- Briefing time.
- Notification categories.
- Per-member consent.
- Preview/privacy preference.

**Done when:** Notification generation can explain why a message was or was not emitted.

---

## Phase 2: Reliable assistant loop

**Goal:** Make Hearthstate reliably convert messy input into useful shared state.

### P2.1 Build a capture inbox as the universal entry point

Consolidate dashboard, Photon, web, email, and later mobile input into the same Inbox model. Preserve original text, source, actor, timestamp, and suggested interpretation.

**Done when:** Every capture has a traceable source and can be reviewed before conversion.

### P2.2 Add confirmation-first suggestions

For ambiguous input, suggest one or more records without silently creating them:

- Task.
- Calendar event.
- Meal.
- Grocery item.
- Linked preparation tasks.

**Done when:** A suggestion can be accepted, edited, rejected, or left unresolved, with all decisions in activity history.

### P2.3 Complete the mutation language surface

Support and test:

- Complete task.
- Assign task.
- Rename task.
- Move event.
- Remove grocery.
- Show recent changes.
- Undo last reversible action.
- Ask for conflicts.

Next additions:

- “Change the cook.”
- “Make this private.”
- “Split this into three tasks.”
- “What changed since yesterday?”
- “What can we prepare before Saturday?”

**Done when:** Each command has a success, ambiguity, not-found, and privacy test.

### P2.4 Deliver briefings through a real scheduler

The current code composes briefings but deliberately does not claim transport delivery. Add a scheduler and delivery adapter with:

- Quiet hours.
- Daily deduplication.
- Per-member preferences.
- Delivery record.
- Retry and failure status.
- No duplicate delivery under concurrent runs.

**Done when:** A briefing can be generated, claimed atomically, delivered once, and audited.

### P2.5 Improve conflict detection

Add:

- Explicit event durations.
- Travel buffers when locations exist.
- Task deadline collisions.
- Per-person conflict scope.
- Resolution state.

Do not claim travel-aware conflicts until locations and travel-time data exist.

**Done when:** A household can distinguish a real conflict from two events assigned to different people.

---

## Phase 3: Integrations and data portability

**Goal:** Fit Hearthstate into the tools households already use.

### P3.1 External calendar sync

Start with read-only imports from Google Calendar, Apple Calendar, and Outlook. Add write-back only after identity, permissions, and conflict handling are stable.

**Done when:** Imported events retain source, external ID, last-sync time, and read/write policy.

### P3.2 Email and school-note capture

Create an inbound email address or forwarding workflow that turns invitations and notices into Inbox suggestions. Do not silently add events from email.

**Done when:** A forwarded event produces a reviewable suggestion with source provenance.

### P3.3 Voice and photo capture

Support:

- Voice memo to Inbox text.
- Photograph of a handwritten grocery list.
- Receipt capture as a later experiment.
- School-note OCR as a later experiment.

**Done when:** The user can see the original media, extracted text, confidence, and suggested actions before conversion.

### P3.4 Grocery provider boundary

Keep the current curated matcher as the safe fallback. Add a policy-compliant retailer adapter with:

- Rate limits.
- Provenance.
- Stale-price labeling.
- Manual-price preservation.
- Fail-closed matching.

**Done when:** No low-confidence match changes a household's list or budget silently.

---

## Phase 4: Mobile companion

**Goal:** Make high-frequency household actions fast on a phone.

### P4.1 Mobile-first web/PWA pass

Before native code:

- Audit all capture and task flows at phone width.
- Add installable PWA metadata.
- Add offline-safe read behavior where practical.
- Make grocery mode usable one-handed.
- Add browser notification experiments.

**Done when:** Pilot households can capture, complete, and shop from a phone without needing the desktop dashboard.

### P4.2 iOS companion MVP

Build only:

- Sign-in and household switching.
- Today / What needs attention?
- Quick capture.
- Grocery list.
- Task completion.
- Calendar glance.
- Push notification preferences.
- Share Sheet capture.
- Voice capture.

**Done when:** A pilot household can use the iOS app for the five most frequent actions without opening the web app.

### P4.3 iOS widgets and Shortcuts

Initial widgets:

- What needs attention?
- Next event.
- Grocery list.
- Dinner tonight.

Initial Shortcuts:

- Add grocery.
- Capture household note.
- Show today.
- Mark task done.

**Done when:** A household member can perform a useful action from the Home Screen or Share Sheet in under ten seconds.

### P4.4 Android companion

Choose React Native/Expo if cross-platform delivery is more valuable than a deeply native iOS first release. Choose SwiftUI first only if iOS-specific widgets and Shortcuts are the immediate differentiator.

**Decision gate:** Do not start Android until pilot data shows that mixed-device households are blocking adoption or retention.

---

## Phase 5: Paid pilot and product-market evidence

**Goal:** Test whether Hearthstate earns repeated use and payment.

### Pilot shape

- 20 households.
- Eight weeks.
- $49 founding annual price or $6.99 monthly.
- Weekly product review.
- No lifetime plan.

### Success signals

Target signals, not promises:

- 15 of 20 households invite another member.
- 10 of 20 remain active at week eight.
- At least 5 use Hearthstate several times per week.
- At least 5 pay or renew.
- Users describe reduced coordination work, not just “a nice dashboard.”
- Briefings produce useful actions without notification fatigue.

### Stop or change signals

Reconsider positioning or scope if:

- One person uses the product but household members do not participate.
- Users capture information but do not convert or complete it.
- Briefings are ignored or muted.
- Users prefer existing calendar tools and do not value the assistant layer.
- Support and AI costs exceed plausible annual revenue.

# Immediate implementation backlog

Start here when development resumes:

1. **Commercial boundary decision:** Choose hosted deployment target and authentication approach.
2. **Household schema:** Add account/household/membership migrations without breaking the local SQLite test mode.
3. **Authorization tests:** Prove cross-household isolation and private-record filtering.
4. **Invitation flow:** Add owner invite and member acceptance.
5. **Notification preferences:** Store quiet hours, briefing time, and categories.
6. **Briefing delivery record:** Make claims atomic and add a transport interface.
7. **Capture contract:** Define one Inbox payload shared by web, Photon, email, and mobile.
8. **PWA pass:** Make capture and grocery mode mobile-first.
9. **Pilot instrumentation:** Emit the events listed in Phase 0.
10. **Pilot recruitment:** Start interviews before beginning native iOS work.

# Decisions deliberately postponed

- Full native iOS versus React Native/Expo.
- Android timing.
- External calendar write-back.
- Receipt OCR.
- Location sharing.
- Hardware or wall display.
- Household load/fairness scoring.
- Multi-household professional or caregiver plans.
- Exact production cloud provider.

These decisions should follow pilot evidence, not precede it.

# Verification standards for future implementation

Every development task should include:

1. A failing behavior test.
2. The smallest implementation that passes it.
3. Privacy and authorization coverage where records are involved.
4. API and UI verification for user-facing changes.
5. Full regression run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q hearthstate tests
for file in hearthstate/dashboard/*.js; do node --check "$file"; done
git diff --check
```

For deployment changes, also verify:

```bash
systemctl --user is-active hearthstate-dashboard.service
curl --fail --silent --show-error http://vnic.tail015325.ts.net:8788/health
```

# Research sources

Pricing and competitor claims were checked against current official pages where available:

- Cozi plans: https://www.cozi.com/compare-plans/
- Cozi Max: https://www.cozi.com/cozi-max/
- FamilyWall Premium: https://www.familywall.com/premium.html
- Maple plans and sunset notice: https://www.growmaple.com/plans
- OurCal privacy positioning: https://ourcal.com/end-to-end-encryption-e2ee
- Skylight Calendar Plus: https://www.skylightframe.com/products/calendar-skylight-plus
- Hearth Display membership: https://hearthdisplay.com/pages/membership
- Hearth Display product page: https://hearthdisplay.com/products/hearth-display
- Cozi App Store listing: https://apps.apple.com/us/app/cozi-family-organizer/id407108860
- FamilyWall App Store listing: https://apps.apple.com/us/app/familywall-family-organizer/id496889629
- Apple Small Business Program: https://developer.apple.com/app-store/small-business-program/
- Apple notification guidance: https://developer.apple.com/design/human-interface-guidelines/notifications
- Apple widget guidance: https://developer.apple.com/design/human-interface-guidelines/widgets/

Prices change. Re-check official pricing before implementing billing or publishing a comparison page.
