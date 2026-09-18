# Simple Content Plan Markdown Format (v1)

This repo supports a simple, strict markdown format for `content_plan.md`.

The goal is:
- easy to write by hand
- easy to parse reliably
- stable enough for automation (weekly execution, approvals, scheduling)

## Required Header

Use these exact keys at the top of the file:

```md
# Content Plan v1

Start Date: YYYY-MM-DD
Timezone: Region/City
Duration Weeks: 12
Review Day: Saturday
Buffer Weeks: 1
```

Notes:
- `Start Date` is the week 1 anchor date.
- `Timezone` should be an IANA timezone (example: `America/Los_Angeles`).
- `Duration Weeks` is usually `12` for a 3-month plan.
- `Buffer Weeks` should usually be `1` (one full week ready ahead).

## Weekly Block Format

Each week must use this exact structure:

```md
## Week NN
Theme: ...
Objective: ...
Audience: item1,item2,item3
Twitter: type | angle
Twitter: type | angle
LinkedIn: type | angle
CTA: ...
```

Rules:
- Week header must be `## Week NN` with zero-padded week number (`01`, `02`, ...).
- `Theme`, `Objective`, `Audience`, and `CTA` are single-line fields.
- `Audience` is a comma-separated list.
- Add one deliverable per line using:
  - `Twitter: <type> | <angle>`
  - `LinkedIn: <type> | <angle>`
- Repeat `Twitter:` and `LinkedIn:` lines as needed.

## Allowed Deliverable Types (recommended)

Use these lowercase types for consistency:
- `thread`
- `single`
- `long_form`
- `carousel`
- `field_note`

## Example

Use the full example here:
- `examples/content_plan.simple.example.md`

Copy this into your project plan file:
- `data/projects/<project_id>/content_plan.md`

