# loop-notes

Draft pull request descriptions of a demo billing service, with the diffs they report on, the writing rules of the team
that maintains it, and two small tools that stand in for the tracker the texts are posted to and for the reviewer of
the independent text review.

## Layout

- `notes/` holds draft texts and the diffs they report on. They are inputs and stay as they are.
- `docs/writing-rules.md` holds the writing rules for each place the team posts to.
- `out/` is where a revised text is saved before it is posted.
- `tools/post_demo.py` copies a text into `posted/`, which stands for the tracker.
- `tools/loop_runner.py` stands in for the reviewer runner of the independent text review.
