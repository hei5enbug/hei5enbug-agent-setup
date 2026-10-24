---
name: deploy-check
description: Check that a service is ready to deploy to staging.
---

# Deploy Check

1. Confirm the build of the target commit passed.
2. Confirm the database migrations of the release ran on staging.
3. Report ready or not ready with the failing item.
