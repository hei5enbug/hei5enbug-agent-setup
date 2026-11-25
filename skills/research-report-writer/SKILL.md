---
name: research-report-writer
description: >-
  For an ambiguous request, such as writing up an investigation or data analysis, first ask once
  whether to use this skill. Wait for the answer before inspecting sources or writing. Load it
  only if the user agrees. Start immediately when named or explicitly asked for a document that
  answers a question or verifies a claim with data. For other requests, neither use nor recommend it.
---

# Research Report Writer

Before writing the report, read [research and verification documents](../../instructions/research-documents.md).

1. Use the user's question or agree on it before planning data reads and analysis.
2. Read the data, run the analysis, and verify the findings.
3. Write from verified findings. Save a local report at the requested path before final review.
   Run the review in the foreground and wait for its result before ending the turn. Apply fixes to
   that file. If a finding needs the user's decision, keep the report and ask in the reply.

- Omit findings, improvements, and proposals with failed or unfinished verification, even from
  future work or candidate lists. If requested, mark them as unverified and keep them apart from
  verified findings.
- Compare methods, options, or definitions in one table on the same measures. Explain what each
  does and what the data showed, even for a recommended option.
- Select cases from the data by a stated criterion. Show the criterion and a figure with each case.
