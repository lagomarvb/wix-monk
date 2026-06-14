# Filtering specification

Each entry in `config.json` describes one Listmonk list and the Wix contacts
that should belong to it. List names are matched exactly. A missing list is
reported during a dry run and created with `--yes` or after interactive
confirmation.

Always run with `--dry-run` after changing a filter:

```bash
wix-monk sync --config config.json --dry-run
```

Before editing a list, use the read-only commands in
[DISCOVERY.md](DISCOVERY.md) to inspect exact live field values and test a
criteria expression independently.

## List configuration

The top-level `criteria` key is optional. When present, it is combined with
every list's own criteria and acts as a global contact filter.

Every list requires a unique `name` and a `criteria` expression. The remaining
keys control Listmonk list creation or override consent handling:

| Key | Required | Default | Meaning |
| --- | --- | --- | --- |
| `name` | yes | | Exact Listmonk list name |
| `criteria` | yes | | Eligibility expression for this list |
| `consent` | no | global policy | Per-list consent override |
| `type` | no | `private` | `private` or `public` |
| `optin` | no | `single` | `single` or `double` |
| `description` | no | managed description | Description used when creating the list |
| `tags` | no | `["wix-monk"]` | Tags used when creating the list |

Unknown keys and duplicate list names are rejected. Existing Listmonk lists
are reused by exact name; creation options only apply when a list is missing.

Example global filter that excludes `.local` addresses:

```json
{
  "criteria": {
    "not": {
      "field": "email",
      "matches_regex": "@[^@]+\\.local$"
    }
  },
  "lists": [
    {
      "name": "All Wix Contacts",
      "criteria": {"field": "email", "is_empty": false}
    }
  ]
}
```

## Eligibility and consent

List membership has two independent gates:

1. `criteria` determines whether a Wix contact is eligible for the list.
2. `consent` determines whether an eligible contact may be added as confirmed.

A contact must pass both gates. Filtering on `subscription_status` inside
`criteria` does not override the consent policy. Existing Listmonk
unsubscribes and global blocklisting are always preserved.

The default consent policy is:

```json
{
  "consent": {
    "subscribed_statuses": ["SUBSCRIBED"],
    "unsubscribed_statuses": ["UNSUBSCRIBED"]
  }
}
```

A list can override the allowed Wix statuses without changing other lists:

```json
{
  "name": "Members",
  "criteria": {"field": "is_member", "equals": true},
  "consent": {
    "subscribed_statuses": ["SUBSCRIBED", "NOT_SET"]
  }
}
```

Statuses not present in either consent array are unknown. Unknown contacts are
not added and are removed from existing managed membership without recording
an unsubscribe.

## Expressions

A `criteria` expression is either a predicate or a boolean combination of
other expressions.

All conditions must match:

```json
{
  "all": [
    {"field": "is_member", "equals": true},
    {"field": "deliverability_status", "equals": "VALID"}
  ]
}
```

At least one condition must match:

```json
{
  "any": [
    {"field": "is_member", "equals": true},
    {"field": "active_pricing_plan", "equals": true}
  ]
}
```

Exclude contacts matching a condition:

```json
{
  "not": {
    "field": "deliverability_status",
    "in": ["BOUNCED", "INACTIVE", "SPAM_COMPLAINT"]
  }
}
```

`all`, `any`, and `not` can be nested to any practical depth. Empty `all` and
`any` arrays are rejected to avoid accidental broad matches.

## Supported fields

| Field | Type | Meaning |
| --- | --- | --- |
| `email` | string | Normalized primary email address |
| `name` | string | Selected Wix/member display name |
| `subscription_status` | string | Merged Wix email status, such as `SUBSCRIBED`, `UNSUBSCRIBED`, or `NOT_SET` |
| `deliverability_status` | string | Wix deliverability status |
| `is_member` | boolean | Linked to an approved Wix Members account |
| `member_status` | string | Selected Wix access status: `UNKNOWN`, `PENDING`, `APPROVED`, `BLOCKED`, or `OFFLINE` |
| `active_pricing_plan` | boolean | Has at least one currently usable pricing-plan order |
| `active_plan_names` | string array | Exact names of active pricing plans |
| `active_plan_ids` | string array | IDs of active pricing plans |
| `contact_ids` | string array | Merged Wix contact IDs |
| `member_ids` | string array | Linked Wix member IDs |
| `phone_numbers` | string array | Phone numbers, preferring E.164 format when Wix provides it |
| `address_lines` | string array | Street-address lines |
| `cities` | string array | Address cities |
| `postal_codes` | string array | Address ZIP or postal codes |
| `subdivisions` | string array | State/region codes such as `US-VA` |
| `countries` | string array | Country codes such as `US` |
| `addresses` | address array | Structured tagged address records |
| `label_keys` | string array | Wix contact label keys |
| `segment_ids` | string array | Wix segment IDs attached to the contact |
| `locales` | string array | Wix locales such as `en` or `en-US` |
| `source_types` | string array | Contact source types such as `WIX_FORMS` |

String comparisons are case-insensitive by default. Add
`"case_sensitive": true` to a predicate when exact case matters. Exact plan
name matching compares the whole name; it is not a substring match.

For example, select members who can log in:

```json
{"field": "member_status", "equals": "APPROVED"}
```

Or select known statuses that cannot currently log in:

```json
{
  "field": "member_status",
  "in": ["PENDING", "BLOCKED", "OFFLINE"]
}
```

`UNKNOWN` means Wix did not provide the status because the API caller lacked
sufficient permission. It should not be treated as approved.

For pricing plans, currently usable means an `ACTIVE` order or a `CANCELED`
order that remains usable until a future `NEXT_PAYMENT_DATE`. `PENDING`,
`PAUSED`, `DRAFT`, and `ENDED` orders do not qualify.

## Operators

Scalar fields support:

| Operator | Example |
| --- | --- |
| `equals` | `{"field": "is_member", "equals": true}` |
| `not_equals` | `{"field": "member_status", "not_equals": "BLOCKED"}` |
| `in` | `{"field": "subscription_status", "in": ["SUBSCRIBED", "NOT_SET"]}` |
| `not_in` | `{"field": "deliverability_status", "not_in": ["BOUNCED", "INACTIVE"]}` |
| `contains_text` | `{"field": "email", "contains_text": ".gov"}` |
| `starts_with` | `{"field": "email", "starts_with": "board."}` |
| `ends_with` | `{"field": "email", "ends_with": "@example.org"}` |
| `matches_regex` | `{"field": "email", "matches_regex": "^[^@]+@example\\.org$"}` |
| `is_empty` | `{"field": "name", "is_empty": false}` |

Array fields support:

| Operator | Meaning |
| --- | --- |
| `contains` | Contains one exact value |
| `contains_any` | Contains at least one configured value |
| `contains_all` | Contains every configured value |
| `contains_regex` | At least one array value matches the regex |
| `is_empty` | Has no values when `true`; has values when `false` |

### Structured addresses

The flattened fields such as `postal_codes`, `cities`, and `address_lines`
answer contact-level questions. For example, this matches a contact with any
address in ZIP `23456`:

```json
{"field": "postal_codes", "contains": "23456"}
```

Use `addresses` with `any_match` when several conditions must apply to the
same address. Address item fields are `tag`, `address_line`,
`formatted_address`, `city`, `postal_code`, `subdivision`, and `country`.

```json
{
  "field": "addresses",
  "any_match": {
    "all": [
      {"field": "tag", "equals": "HOME"},
      {"field": "postal_code", "equals": "23456"}
    ]
  }
}
```

This will not combine a `HOME` tag from one address with ZIP `23456` from a
different billing or shipping address. Wix address tags observed in the live
data include `HOME`, `BILLING`, `SHIPPING`, and `UNTAGGED`.

Exclude contacts with any billing address outside Virginia:

```json
{
  "not": {
    "field": "addresses",
    "any_match": {
      "all": [
        {"field": "tag", "equals": "BILLING"},
        {"field": "subdivision", "not_equals": "US-VA"}
      ]
    }
  }
}
```

Regex matching uses Python regular-expression syntax and searches within each
field value. Use `^` and `$` when the whole value must match. It is
case-insensitive by default, like other string operators. Patterns are
compiled during configuration validation and limited to 256 characters.
Prefer exact plan IDs where possible; regex is most useful for controlled
naming conventions or email domains.

Examples:

```json
{"field": "email", "matches_regex": "^[^@]+@(example\\.org|example\\.com)$"}
```

```json
{
  "field": "active_plan_names",
  "contains_regex": "^(Annual|Lifetime) Lago Mar .* Membership$"
}
```

## Exact pricing-plan lists

Plan IDs are the most stable filter because Wix can rename a plan:

```json
{
  "name": "Annual plan members",
  "criteria": {
    "all": [
      {"field": "active_pricing_plan", "equals": true},
      {"field": "active_plan_ids", "contains": "your-wix-plan-id"}
    ]
  },
  "consent": {
    "subscribed_statuses": ["SUBSCRIBED", "NOT_SET"]
  },
  "type": "private",
  "optin": "single"
}
```

An exact plan name can be used when the ID is not known:

```json
{
  "field": "active_plan_names",
  "contains": "Annual Lago Mar Civic League Membership"
}
```

Match any of several plans:

```json
{
  "field": "active_plan_names",
  "contains_any": [
    "Annual Lago Mar Civic League Membership",
    "Civic League Annual Dues",
    "2025 Lago Mar Civic League Membership"
  ]
}
```

Require both a specific plan ID and an approved member account:

```json
{
  "all": [
    {"field": "is_member", "equals": true},
    {"field": "active_plan_ids", "contains": "your-wix-plan-id"}
  ]
}
```

## Common recipes

Approved members, including historical `NOT_SET` records:

```json
{
  "name": "Members",
  "criteria": {"field": "is_member", "equals": true},
  "consent": {
    "subscribed_statuses": ["SUBSCRIBED", "NOT_SET"]
  }
}
```

Subscribed contacts who are not members:

```json
{
  "name": "Subscribed non-members",
  "criteria": {
    "all": [
      {"field": "is_member", "equals": false},
      {"field": "subscription_status", "equals": "SUBSCRIBED"}
    ]
  }
}
```

Members or active plan holders, excluding failed delivery statuses:

```json
{
  "all": [
    {
      "any": [
        {"field": "is_member", "equals": true},
        {"field": "active_pricing_plan", "equals": true}
      ]
    },
    {
      "not": {
        "field": "deliverability_status",
        "in": ["BOUNCED", "INACTIVE", "SPAM_COMPLAINT"]
      }
    }
  ]
}
```

Contacts in a ZIP code with a specific Wix label:

```json
{
  "all": [
    {"field": "postal_codes", "contains": "23456"},
    {"field": "label_keys", "contains": "custom.neighborhood"}
  ]
}
```

Virginia phone numbers stored in E.164 format:

```json
{
  "field": "phone_numbers",
  "contains_regex": "^\\+1(757|804)"
}
```

## Dry-run report

- `eligible_contacts`: contacts matching `criteria`, before consent.
- `eligible_subscribed`: eligible contacts allowed by the effective consent policy.
- `eligible_unsubscribed`: eligible contacts denied by the effective consent policy.
- `eligible_unknown_consent`: eligible contacts whose status is in neither consent array.
- `add`: confirmed memberships that would be added.
- `remove`: memberships removed without recording an unsubscribe.
- `unsubscribe`: memberships changed to unsubscribed because Wix explicitly denies consent.
- `preserve_unsubscribe`: existing Listmonk unsubscribes left untouched.
- `stale_remove`: managed memberships removed because the Wix contact disappeared.

The configuration is validated before Wix or Listmonk API calls. Unknown
fields, unknown operators, conflicting operators, and malformed arrays stop
the run with an `Invalid config` error.
