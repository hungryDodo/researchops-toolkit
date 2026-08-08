# Development-led R&D protocol

## Primary objective

Deliver a maintainable, testable, deployable outcome under explicit cost, reliability, security, and operational constraints. Research is a means to reduce decision uncertainty, not an excuse to preserve every novel route.

## Option pruning

Prefer the simplest route that satisfies the acceptance contract. A niche or complex technique remains a candidate only when its expected benefit justifies implementation, maintenance, integration, observability, and rollback cost.

## Minimality ladder

1. Is the change necessary?
2. Is equivalent code or configuration already present?
3. Can deletion or consolidation solve it?
4. Can the language/runtime standard library solve it?
5. Can an already installed dependency solve it?
6. Is a new abstraction or dependency justified by repeated use or a stable boundary?

Never trade away safety, data integrity, accessibility, testability, or explicit user scope merely to reduce line count.

## Research-led contrast

Research-led engineering may retain high-risk or impractical candidates when they answer a narrow scientific question. Development-led work must account for the whole delivery surface and can reject a scientifically interesting route whose engineering trade-off is poor.
