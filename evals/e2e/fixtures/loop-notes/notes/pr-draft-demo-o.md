The statement export now rounds each line to cents before it adds them, so the total of a statement equals the sum of its printed lines.

The rounding happens in one helper that the CSV and the PDF export share.

This change follows the report that statement totals were off by a cent.

- Added a test that a statement of three lines with fractions adds up to its printed lines.
- Ran the statement test module: 9 passed.

The statement module was cleaned up along the way.

The change is small and easy to review.
