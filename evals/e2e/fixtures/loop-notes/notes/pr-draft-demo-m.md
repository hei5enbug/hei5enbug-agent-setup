Invoices with a zero total are now skipped by the nightly export, so a customer with only credits no longer gets an empty file.

The skipped customers are listed in the export log with their ids.

This change follows the report that zero-total customers made the nightly export slow.

- Added a test that a zero-total customer produces no file.
- Ran the export test module: 14 passed.

The export module was refactored as part of this work.

The change is small and easy to review.
