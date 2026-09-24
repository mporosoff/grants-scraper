# Same-call email notifications

The FY2027 MURI competition has three official service notices:

| Service | Grants.gov record | Notice |
| --- | --- | --- |
| AFOSR | [363899](https://www.grants.gov/search-results-detail/363899) | NOFOAFRLAFOSR20260002 |
| Army | [363905](https://www.grants.gov/search-results-detail/363905) | W911NF26S1000 |
| ONR | [363906](https://www.grants.gov/search-results-detail/363906) | N0001426SF002 |

The retained official [ONR notice, page 21](https://grants.gov/grantsws/rest/opportunity/att/download/355073#page=21)
names these three submission identifiers together. They are one annual call
for saved-search notification purposes. Their service topics and submission
routes remain distinct catalog records.

`workers/alerts/src/notification-families.js` contains reviewed notification
families. Membership requires the exact source, record, solicitation, sponsor
and annual title. A similar title, another fiscal year, topic, sponsor, or
aggregator default does not establish membership. Additional families or cycles
require source-backed review; this is not a general fuzzy-title merge.

A saved search sends one Strong-match notification for this annual family.
The main notice and reasons belong to an actually matching record. The email
also lists the available related service notices with their individual links
and dates; those related notices are not all asserted to be Strong matches.
An unresolved next submission remains unresolved even when the structured
source supplies a closing date. Immediate mail and weekly digests use the same
bounded, escaped public-only notice fields.

The existing subscription state retains a once-qualified family marker. A
stable per-subscription event key protects concurrent evaluation and recovery
after enqueue. Existing listing qualifications and notification history prevent
an upgrade from replaying this call. The marker survives normal terminal-email
retention and temporary loss of matching. Reactivation uses the existing
subscription baseline lifecycle. Old delivery statuses, reservations, payloads
and provider idempotency keys are preserved.

Explicit opportunity watches still deliver service-specific amendments,
deadline and status changes. Independent saved searches and recipients retain
their separate subscriptions. Catalog identity, scientific interpretation and
search ranking are unchanged.

Alerts deployment follows successful completion of the immutable catalog/Pages
release, instead of racing its initial push. It checks out protected default
branch event SHA, rechecks current main, compares the served catalog and pages,
then uses the existing deployment classification, migration, health and rollback
gates. A failed or unverified publication cannot authorize a Worker update.

Regression coverage includes the retained public identities, separate cursor
pages, actual matching-service selection, later arrivals, legacy notifications,
concurrent enqueue, crash recovery, delivery retention, unrelated cycles and
topics, explicit watches, independent subscriptions, and safe HTML/text output.
No real email is sent by these tests.
