# Private tracker detail

Rules for a draft when `target.public` is false. Read this before drafting such an issue.

Coding agents working on the owning plugin read these issues, so include every detail that helps them do the work, in
every section, including Proposal and Acceptance criteria:

- real ticket keys, repository names, file paths inside repositories, branch names, and commit hashes;
- the names of other plugins, products, and services involved, and how each relates to the gap;
- real values in place of fictional ones, so an acceptance criterion can run as written, except where the owning
  repository restricts what an evaluation fixture may contain, as in the last rule below.

Name the case's real ticket keys, repositories, and other plugins in the Proposal itself, where a rule applies to
them or in a line that says which ticket, repository, and plugins the rules come from and apply to; Observations and
Evidence alone are not enough.

Still leave out, whatever the tracker:

- a secret, credential, token, password, key, or personal data;
- a local absolute path, a home folder, and a user name; write a path relative to its repository instead;
- every sentence that the content-rules file excludes. That file keeps narrowing the issue, and a private tracker
  never authorizes what it excludes.

Two more rules for a private tracker:

- Under the condition that the draft cites a page, file, or message, cite it without the name of any person, such as a
  heading that carries a name. Before filing, search the draft for each person collected in step 1 and for every
  email address, and rewrite until none remains.
- Check the owning repository's instruction files, such as `AGENTS.md` or `CLAUDE.md`. Under the condition that they
  restrict what an evaluation fixture may contain, keep the real case in Observations and Evidence, and say in
  Acceptance criteria that the fixtures replace it with values those instructions allow.
