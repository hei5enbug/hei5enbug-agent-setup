# Operator guide: frontier concurrency

Do not attach this file to the agent prompt. Prepare a disposable copy of
`evals/files/frontier-race` for each session.

For the concurrent claim case, start two independent sessions on the same first ticket and verify that only one
owns its atomic lock. After the winning session claims `01-backoff-policy.md`, edit its Question text before work
begins. The session must re-read and use the current question. Then let two sessions resolve different open
tickets so their map updates contend. Verify that each map writer claims `map.md`, re-reads after acquiring it,
and preserves the other completed decision. Keep any unreadable or failed transaction locked and report its
recovery point. If an independent session or safe concurrent edit is unavailable, record that branch as
unverified.
