---
name: share-solution
description: Distill a solution the user and Claude just worked out into an anonymized, reusable SolvePool room and publish it as a GitHub Issue with the solvepool_share tool. Use when the user asks to share, publish or save a solution to SolvePool ("condividi questa soluzione", "share this to the pool", "make this a room") or accepts the offer made by the use-shared-solution skill. Always shows the draft and waits for an explicit yes before publishing.
tags: ["solvepool", "shared-solutions", "privacy"]
---

# Share a solution

A room is **public forever** in GitHub's history. The user is the author; you prepare a draft that helps a stranger and reveals nothing about this user, their machine or their organization.

## Steps

1. **Distill.** From the conversation, write:
   - **Title**: the problem in one full sentence, as a stranger would search it ("Apify standby Actor returns 502 until the readiness probe is answered").
   - **Problem**: context and symptoms, depersonalized, three to six lines.
   - **Solution**: numbered reusable steps, the reasoning that matters, the pitfalls, the rejected alternatives if useful. Replace every value that changes from person to person with a `{{variable}}`.
   - **Open variables**: one line per `{{variable}}`: `name — what it means · typical values`.
   - **Verification**: how the reader checks the result is right.
   - **Example prompts**: one to three anonymized prompts this room answers, including the user's own request rewritten without personal details.
   - **Tags**: up to five short lowercase words (stack, domain, task).

2. **Anonymize with the checklist.** Remove or replace with variables: person and company names, emails, phone numbers, API keys and tokens (also inside code), file paths containing user names, hostnames, internal URLs, repository names of the user's organization, customer or invoice data, anything under NDA. Keep only what a public forum post would contain. Prefer neutral placeholders (`{{customer}}`, `{{db_name}}`) over invented fake names.

3. **Show the draft** to the user exactly as it will be published, then ask: "Publish this as a public room in {{repo}}? (yes / edit / no)". **Never call `solvepool_share` before an explicit yes.** Apply requested edits and show the draft again if the changes are substantial.

4. **Publish** with `solvepool_share` (title, problem, solution, variables, verification, example_prompts, tags). The tool refuses text that still looks personal or secret and lists what it found: fix it and retry. If it reports that a very similar room already exists, show that room to the user and suggest commenting there (link) instead of opening a twin; open a new one with `force=true` only if the user insists that the problem is different.

5. **Report** the URL of the new room in one line.

## Rules

- No token, no publish: if the tool answers that a GitHub token is needed, relay the two ways to provide it (GITHUB_TOKEN environment variable, or `gh auth login`) and stop.
- The user may write in Italian or English; keep the five section headings as the tool renders them and write the content in the language the user prefers.
- Do not pad. A room is good when a stranger can act on it in five minutes.
- Private material belongs in a private rooms repository configured by the user's team, never in the public default.
