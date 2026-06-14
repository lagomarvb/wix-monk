# Data discovery and filter testing

The discovery commands are read-only. They query Wix but do not require a
`config.json` file and do not connect to Listmonk. Values are produced from the
same normalized contact records used by synchronization, so displayed values
can be copied directly into criteria expressions.

## Show the filter schema

```bash
wix-monk schema
```

This lists every field, its type, and the operators valid for that field. It
does not require credentials or network access.

Machine-readable output:

```bash
wix-monk schema --json
```

## Show observed values

```bash
wix-monk values
```

The default output includes useful low-risk fields such as consent statuses,
deliverability statuses, member statuses, active plan names, and active plan
IDs. Names, email addresses, contact IDs, and member IDs are omitted by
default.

Inspect one field:

```bash
wix-monk values subscription_status
wix-monk values member_status
wix-monk values active_plan_names
wix-monk values active_plan_ids --json
```

A sensitive field can be requested explicitly:

```bash
wix-monk values email
```

## Show pricing plans

```bash
wix-monk plans
```

This pairs each observed plan name with its plan ID and reports total orders,
currently usable orders, and order statuses. The output field remains named
`active_term_orders`. It includes `ACTIVE` orders and future-effective
`CANCELED` orders, and excludes `PENDING`, `PAUSED`, `DRAFT`, and `ENDED`.
The command reads pricing-plan orders,
so a Wix plan that has never had an order will not appear. Each result includes
copy-ready criteria using either the plan ID or exact plan name.

Plan IDs are preferable to names in long-lived filters:

```json
{"field": "active_plan_ids", "contains": "the-plan-id"}
```

## Inspect members

Summarize all approved Wix members without printing personal details:

```bash
wix-monk members
```

Explicitly show up to 50 member records:

```bash
wix-monk members --show-contacts --limit 50
```

Names and email addresses appear only when `--show-contacts` is supplied.

## Audit duplicates and member/contact links

Show counts without personal data:

```bash
wix-monk duplicates
```

Show the Wix records behind each issue:

```bash
wix-monk duplicates --show-records
```

Machine-readable detailed output:

```bash
wix-monk duplicates --show-records --json
```

The audit detects:

- Multiple Wix Contact records with the same normalized email address.
- Multiple Wix Member accounts with the same login email.
- A Member whose linked Contact has a different email address.
- A Member linked to a Contact only through matching email fallback.
- A Member with no matching Contact.

Detailed output includes personal data and Wix record IDs so the records can
be found and merged in Wix. A warning is written to stderr.

## Test an expression

Test criteria directly without editing `config.json`:

```bash
wix-monk query \
  --criteria '{"field":"active_plan_names","contains":"Annual Lago Mar Civic League Membership"}'
```

Test a nested expression stored in a file:

```bash
wix-monk query --criteria-file criteria.json
```

Show matching contacts when needed:

```bash
wix-monk query \
  --criteria-file criteria.json \
  --show-contacts \
  --limit 100
```

The query summary reports the number of matches and breakdowns by consent,
deliverability, membership, and active pricing plan. The same validation and
matching engine used by synchronization evaluates the expression.

## Create a live reference snapshot

```bash
wix-monk snapshot --json > wix-filter-snapshot.json
```

The snapshot contains:

- The filter schema and supported operators.
- Observed non-sensitive values and counts.
- Pricing-plan names, IDs, order counts, and statuses.

It deliberately excludes contact names and email addresses. Regenerate it
when Wix plans, member states, or contact statuses change.

To export every normalized contact record, including names, email addresses,
phones, addresses, labels, segments, membership state, active plans, and the
attributes sent to Listmonk:

```bash
wix-monk snapshot --json --include-contacts > wix-contacts.json
```

This option writes a personal-data warning to stderr. The JSON file remains
valid because JSON is written to stdout. Treat the resulting file as sensitive
and keep it out of source control, shared logs, and unattended backups.

Addresses are exported as structured records retaining their Wix tag and
components. This makes it possible to distinguish home, billing, shipping,
and untagged addresses rather than treating all address values as one flat
record.

## Recommended workflow

1. Run `schema` to see the available fields and operators.
2. Run `values` or `plans` to copy exact live values.
3. Build a criteria expression in a small JSON file.
4. Run `query --criteria-file ...` until the match count is correct.
5. Place the expression in `config.json`.
6. Run `sync --config config.json` and review consent and membership changes.
7. Use `sync --config config.json --yes` only after the dry run is correct.
