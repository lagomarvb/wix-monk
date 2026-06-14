# Architecture

The package separates transport, normalization, policy, orchestration, and
presentation. Dependencies point inward toward domain models and pure logic.

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `integrations/clients.py` | Wix and Listmonk API clients |
| `integrations/ports.py` | Small gateway protocols used by application services |
| `integrations/adapters.py` | Normalize and reconcile Wix/Listmonk API records |
| `integrations/datasets.py` | Load and expose normalized Wix and Listmonk data |
| `integrations/services.py` | Lazily load integration datasets |
| `domain/models.py` | Domain data structures |
| `domain/filtering.py` | Validate and evaluate criteria expressions |
| `domain/policy.py` | Pure consent and list-membership planning rules |
| `domain/reporting.py` | Per-list summary calculations and formatting |
| `config/loading.py` | Validate JSON configuration into typed definitions |
| `discovery/calculations.py` | Pure discovery, query, and duplicate-audit calculations |
| `discovery/commands.py` | Read-only command presentation |
| `sync/service.py` | Synchronization use case and Listmonk mutations |
| `context.py` | Runtime streams, logger, and integration settings |
| `cli.py` | Argument parsing, environment composition, and dispatch |

## Design rules

1. API-specific dictionaries are normalized at the adapter boundary.
2. Consent policy and eligibility filtering remain independent.
3. Policy functions do not perform I/O.
4. Application services depend on gateway protocols, not HTTP implementation details.
5. The CLI contains no synchronization or filtering business logic.
6. Dry-run and apply use the same planned `ContactPlan` objects.
7. Discovery uses the same `WixDataset` and filter evaluator as synchronization.
8. Existing Listmonk unsubscribe and blocklist decisions remain authoritative.

## Extension guidance

New Wix data should be normalized onto `WixContact` in
`integrations/adapters.py`, exposed
through the filter schema only when its type and semantics are stable, and
covered with adapter and filtering tests. Avoid making raw Wix JSON directly
filterable because that couples configuration files to undocumented API
shapes.

New external systems should implement a small protocol in
`integrations/ports.py`. Domain policy should not import concrete clients.

New CLI commands should delegate to an application service or command handler;
they should not call several APIs and implement business decisions directly in
`cli.py`.
