---
name: humanizer
description: Use when editing or reviewing user-facing text to remove obvious AI-writing patterns, reduce filler/sycophancy, and keep prose natural without losing meaning or technical accuracy.
license: MIT
compatibility: opencode claude-code
---

## Goal

Rewrite text so it reads like a clear human wrote it, while preserving meaning, structure, technical correctness, and the author's intended tone.

## Use When

- the user asks to humanize, naturalize, or de-AI a draft
- a response, doc, release note, README section, or UX copy sounds stiff, generic, inflated, or chatbot-like
- the main problem is wording quality rather than product logic or code behavior
- a final writing pass is needed after the technical content is already correct

## Do Not Use When

- the task is mainly code, config, schema, commands, or exact error text
- legal, policy, security, or compliance wording must stay exact
- the text is already concise and natural enough
- adding personality would hurt neutral technical/reference writing

## First Steps

- Identify whether the target text is technical, instructional, promotional, conversational, or personal.
- Preserve facts, structure, and coverage before changing style.
- Keep identifiers, commands, paths, flags, API names, and exact quoted strings unchanged unless the user asks otherwise.
- If the user provides a writing sample, match its rhythm and level of formality rather than applying a generic voice.

## Working Rules

- Cut filler, praise, hype, and signposting first.
- Prefer direct statements over inflated framing such as "pivotal," "transformative," or "it's not just X, it's Y."
- Remove chatbot artifacts like "Great question," "I hope this helps," and generic concluding fluff.
- Keep paragraphs and lists proportional to the source unless the user asks for restructuring.
- Do not flatten good writing into sterile writing; neutral technical text should stay plain, while personal writing may keep more voice.
- Avoid rewriting away useful precision, nuance, or caveats that the original actually needs.
- Follow repo style expectations: low-filler, high-signal, technically accurate, and easy to scan.

## Output

When rewriting text:

1. Provide the rewritten version first.
2. If useful, add a very short note naming 1-3 major patterns removed.
3. Do not add an explanation unless the user asks for one.

## Patterns To Watch

- filler openings and closings
- sycophantic tone
- promotional adjectives and significance inflation
- vague attributions
- rule-of-three padding
- em-dash-heavy rhythm
- repetitive abstract nouns like "landscape," "insights," or "transformation"
- tailing negations like "no guessing" instead of a full clause
- diff-anchored phrasing that describes what changed instead of what the thing does

## Evidence / Done

- The rewrite preserves the original meaning.
- AI-sounding filler or hype is materially reduced.
- Technical terms and exact strings that matter remain intact.
- The result fits the target voice better than the source.

## References

- `AGENTS.md`
- `docs/concise-communication-workflow.md`
- `https://github.com/blader/humanizer`
