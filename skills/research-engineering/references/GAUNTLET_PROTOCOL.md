# Gauntlet protocol

## Risk tiers

- Low: local reversible code with deterministic unit checks.
- Medium: shared modules, data conversion, performance measurement, or broad refactors.
- High: research claims, hardware control, destructive cleanup, security/privacy, or expensive campaigns.

Increase independent verification, failure injection, and environment capture with risk. A single passing smoke test is not sufficient for medium/high risk.

## Minimality ladder

Before adding code or dependencies ask: Is the change needed? Does equivalent code exist? Can the standard library/platform solve it? Is an installed dependency sufficient? Can deletion or a smaller interface solve it? Never trade away safety, accessibility, data integrity, measurement validity, or hardware calibration for fewer lines.
