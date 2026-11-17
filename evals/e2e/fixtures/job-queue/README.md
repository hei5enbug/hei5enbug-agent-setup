# job-queue

A file-based job queue for several worker processes, a session refresher, and a store of approvals.

| Module | What it does |
|---|---|
| `jobq.locks` | `FileLock`, an advisory lock on a file, blocking or not. |
| `jobq.queue` | `enqueue` adds a job; `claim_next` hands one pending job to a worker. |
| `jobq.refresh` | `Refresher` sends a refresh command to each session and records the result. |
| `jobq.grants` | `GrantStore` keeps the approvals a session has been given. |
| `jobq.hook` | Reads one hook payload and decides whether the call needs an approval. |

A queue folder holds `pending/`, `running/`, and `done/`; each job is one JSON file named by its id.
