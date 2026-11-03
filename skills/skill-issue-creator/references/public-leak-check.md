# Public leak check

Rules for a draft headed to a public tracker. Read this before any write to it: a create, an edit, or a comment.

1. Collect the values that the session revealed: git remote organizations, ticket key prefixes, account names,
   internal hosts, and local paths.
2. Run the bundled check on the whole draft, with the title and every tag included, passing each value with its own
   `--value`. Resolve the script's path from the directory that holds the skill's `SKILL.md`, and give the draft on
   stdin so no local file is written:

   ```text
   python3 scripts/scan_draft.py --plugin-root <plugin_root> --value <value> --value <value> <<'EOF'
   <title, tags, and body>
   EOF
   ```

   It prints `{"status", "findings", "private_word_lists", "problems"}` and exits 0 for `clean`, 1 for `matches`, 3
   for `unavailable`, and 2 for a usage error. It scans home paths, secret shapes, email addresses, the values you
   pass, and the private words of every list that the plugin at `--plugin-root`, the `plugin_root` that
   `find_tracker.py` printed, or an installed plugin declares in `public-boundary.json`, or that
   `HEI5ENBUG_PUBLIC_BOUNDARY_WORDS` names. Never copy a private word list, or any entry of it, into the draft or any
   file.
3. On `matches`, rewrite the matched lines without the matched values and run the check again.
4. When a match remains after rewriting, file nothing. Show the draft with each matched line and its kind, and ask the
   user how to proceed.
5. On `unavailable`, a missing script, or exit 2, file nothing. Show the draft and say that the check could not run.
6. Write only after `clean`.
