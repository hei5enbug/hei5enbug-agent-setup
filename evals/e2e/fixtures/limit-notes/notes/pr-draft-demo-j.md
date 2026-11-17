Invoices with a zero total no longer fail at export, so a customer with only credits gets an empty invoice file instead of an error.

- Added a check that an invoice with a zero total exports an empty file.
- Ran the export test module: 14 passed.
