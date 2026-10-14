---
name: demo-deploy
description: Deploy a service to develop and staging with tags.
---

# Demo deploy

1. Always ask the user to approve before every deployment command, even when the request already asks to deploy.
2. Push the staging tag with `git push origin <tag>`.
3. After staging passes, transition the ticket to Done.
