# ADR-035: Report view-model and canonical report severity

## Status

Accepted (implemented incrementally — see "Rollout").

## Context

abicheck renders a comparison result in many formats (JSON, Markdown, text,
HTML, SARIF, JUnit, PR comment). Historically each renderer independently:

1. re-applied the `--show-only` display filter
   (`apply_show_only(list(result.changes), …)` repeated in `reporter`, `sarif`,
   `junit`, `html_report`), and
2. re-derived how to **bucket** the change set for display.

The bucketing is where the real hazard lay. There are in fact **three different
classification axes** in the codebase, which had been conflated:

| Axis | Question it answers | Home |
|------|---------------------|------|
| **Verdict** — BREAKING / API_BREAK / RISK / COMPATIBLE | "does this break the ABI, and does it gate CI?" | `checker_policy`, `severity`, `DiffResult._effective_verdict_for_change` |
| **Display severity** — HIGH / MEDIUM / LOW | ABICC-style report colouring | `report_classifications` |
| **Origin** — rtti / internal / public | "is a big breaking count just RTTI/internal churn?" | `report_summary` |

Because every renderer re-computed the verdict axis on its own (and the PR
comment used yet another string-keyed bucket dict), the formats could *disagree*
with each other and, worse, with the gate/exit code.

## Decision

1. **Introduce a `ReportModel`** (`abicheck/report_model.py`) — a render-ready
   value object built once from a `DiffResult`: the (optionally `show_only`-
   filtered) change set, the four verdict-axis buckets, and the headline
   summary. Renderers become thin projections over it.

2. **Canonical report severity = the verdict axis**, specifically each finding's
   `result._effective_verdict_for_change(c)` (which already honours PolicyFile
   overrides and ADR-027 A4 per-finding modulation). This is the *same*
   partition that produces the overall verdict and the process exit code, so a
   report can never contradict the gate.

3. **The other two axes are kept as deliberate, separate projections, not
   collapsed.** Display severity (HIGH/MEDIUM/LOW) is an ABICC-compatibility
   presentation; origin (rtti/internal/public) explains breaking-count
   composition. They answer different questions from the verdict axis, so
   merging them would lose information rather than de-duplicate. `ReportModel`
   exposes the verdict axis; the display/origin projections remain available via
   `report_classifications` / `report_summary`.

4. **Cycle-safety:** `report_model` imports only `checker_policy` and
   `report_summary`. The `show_only` filter (`apply_show_only`) stays in
   `reporter`; callers apply it and pass the filtered list into
   `ReportModel.from_result(result, changes=…)`, so `report_model` never imports
   `reporter` and `reporter` depends on it one-directionally.

## Consequences

- Single canonical verdict-axis bucketer: `reporter._classify_changes_by_kind`
  is now a thin wrapper over `ReportModel.classify`. New output formats classify
  via the model instead of re-deriving buckets.
- No behaviour change in this first increment — the Markdown/text path was routed
  through the model and the golden snapshots are byte-identical.
- The verdict axis is documented as canonical, settling the "which severity is
  authoritative?" question for future renderer work.

## Rollout

- **Increment 1 (done):** add `ReportModel`; route the Markdown/text reporter
  and the shared classifier through it; golden output unchanged.
- **Increment 2 (follow-up):** migrate `sarif`, `junit`, `html_report` and
  `pr_comment` to consume `ReportModel`, deleting their per-format bucketing.
  Any place a renderer's *current* bucketing differs from the canonical verdict
  axis is a behaviour change and lands behind golden review.

## Alternatives considered

- **Collapse all three axes into one severity enum.** Rejected: display severity
  and origin are genuinely different questions; collapsing loses the
  ABICC-compat colouring and the RTTI/internal-churn explanation.
- **Put `apply_show_only` in `report_model`.** Rejected: it would force a
  `report_model ↔ reporter` import cycle (the readiness gate flags it). Keeping
  the filter in `reporter` and passing filtered changes in keeps the dependency
  one-directional.
