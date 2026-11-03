# Private tracker detail

Rules for a draft when `target.public` is false. Read this before drafting such an issue.

Coding agents working on the owning plugin read these issues, so include every detail that helps them do the work, in
every section, including Proposal and Acceptance criteria:

- real ticket keys, repository names, file paths inside repositories, branch names, and commit hashes;
- the names of other plugins, products, and services involved, and how each relates to the gap;
- real values in place of fictional ones, so an acceptance criterion can run as written.

Name the case's real ticket keys, repositories, and other plugins in the Proposal itself, where a rule applies to
them or in a line that says which ticket, repository, and plugins the rules come from and apply to; Observations and
Evidence alone are not enough.

Still leave out, whatever the tracker:

- a secret, credential, token, password, key, or personal data;
- a local absolute path, a home folder, and a user name; write a path relative to its repository instead;
- every sentence that the content-rules file excludes. That file keeps narrowing the issue, and a private tracker
  never authorizes what it excludes.
