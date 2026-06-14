# wix-monk

`wix-monk` synchronizes Wix contacts and pricing-plan membership into selected
Listmonk lists. It treats list eligibility and permission to email as separate
decisions.

## Preference rules

The synchronization is intentionally conservative:

1. A Listmonk global blocklist is never cleared.
2. A Listmonk list unsubscribe is never changed back to confirmed.
3. A Wix `UNSUBSCRIBED` status unsubscribes existing managed memberships.
4. Only explicit Wix `SUBSCRIBED` contacts are added as confirmed by default.
5. Unknown consent or poor deliverability removes managed membership without
   recording a user unsubscribe.
6. Eligibility changes remove only lists declared in the config. Other
   Listmonk lists and attributes are preserved.
7. Subscribers previously sourced from Wix but no longer returned by Wix are
   removed from managed lists. Their subscriber record and unsubscribe history
   are retained.

This means an active paid membership can qualify a contact for a list, but it
cannot override that person's communication preference.

Consent status handling defaults to allowing only `SUBSCRIBED`, denying
`UNSUBSCRIBED`, and treating all other Wix statuses as unknown. It can be
overridden globally with the top-level `consent` configuration or for one list
with a list-level `consent` block. For example, to include Wix members whose
status is `NOT_SET` without doing so for other lists:

```json
{
  "name": "Members",
  "criteria": {"field": "is_member", "equals": true},
  "consent": {
    "subscribed_statuses": ["SUBSCRIBED", "NOT_SET"]
  }
}
```

An explicit `UNSUBSCRIBED` remains denied unless it is deliberately removed
from `unsubscribed_statuses`. Existing Listmonk list unsubscribes and global
blocklisting are always preserved.

## Setup

Python 3.11 or newer is required. Install the project in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

Copy `config.example.json` to `config.json`, then set the required environment
variables:

```bash
export WIX_API_KEY='...'
export WIX_SITE_ID='...'
export LISTMONK_URL='https://listmonk.example.org'
export LISTMONK_USERNAME='...'
export LISTMONK_PASSWORD='...'
```

`WIX_ACCOUNT_ID` is optional. It is mostly there for possible future use or
for Wix endpoints that require an account-level identifier. The current
site-level sync and discovery calls use `WIX_SITE_ID`.

Run a dry-run first:

```bash
wix-monk sync --config config.json --dry-run
```

Run the sync interactively:

```bash
wix-monk sync --config config.json
```

Apply without prompting:

```bash
wix-monk sync --config config.json --yes
```

Missing configured lists are reported during a dry run and created when the
sync is applied. They default to private, single opt-in lists tagged
`wix-monk`. The optional config keys `type`, `optin`, `description`, and
`tags` customize their creation. Existing lists with the same exact name are
reused.

Dry-run and apply output include a section for each managed list with Wix
eligibility and consent counts, planned membership changes, and current versus
resulting confirmed membership.

All lists use the same declarative expression language. For nested `all` /
`any` / `not` filters, supported fields and operators, regex matching, consent
overrides, exact pricing-plan recipes, and report definitions, see
[FILTERING.md](FILTERING.md).

If you need a global contact filter, add a top-level `criteria` key in
`config.json`. It is combined with every list-specific `criteria` expression.

To inspect live Wix values, list observed pricing plans, summarize members,
audit duplicate member/contact records, test one expression, or create a
reusable JSON snapshot, see
[DISCOVERY.md](DISCOVERY.md).

Filters can use normalized names, email addresses, phone numbers, address
components, ZIP/postal codes, Wix labels, segments, locale, source type,
membership state, and active pricing plans. An explicit
`snapshot --json --include-contacts` export is available for authorized local
inspection; the default snapshot remains aggregate-only.

Pricing-plan lists can be restricted by exact plan names:

```json
{
  "name": "Annual civic league plans",
  "criteria": {
    "field": "active_plan_names",
    "contains_any": [
      "Annual Lago Mar Civic League Membership",
      "Civic League Annual Dues",
      "2025 Lago Mar Civic League Membership"
    ]
  }
}
```

Plan IDs are preferable for long-term configuration because a Wix plan can be
renamed. Use the `active_plan_ids` field with `contains`, `contains_any`, or
`contains_all`. Active plan IDs and names are written to the subscriber's
Listmonk attributes.

A pricing-plan order counts as active when Wix reports `ACTIVE`, or when a
`CANCELED` order remains usable until its future `NEXT_PAYMENT_DATE` end date.
`PENDING`, `PAUSED`, `DRAFT`, and `ENDED` orders do not qualify.

Duplicate Wix contacts are merged by normalized email. Member-linked contacts
take precedence for identity fields, any explicit Wix unsubscribe wins for
consent, and orders are joined through both contact and member IDs. The merged
Wix contact/member/order IDs and active plan names are retained as Listmonk
attributes for auditing.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Optional development checks:

```bash
# Required when running directly from a source checkout
export PYTHONPATH=src

python3 -m pip install -e '.[dev]'
ruff check wix_monk tests
pyflakes wix_monk tests
vulture wix_monk tests --min-confidence 80
```

Module responsibilities and dependency rules are documented in
[ARCHITECTURE.md](ARCHITECTURE.md).
