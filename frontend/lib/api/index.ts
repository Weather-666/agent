export * from "./audit";
export * from "./featured";
export * from "./auth";
export * from "./chat";
export * from "./expert-categories";
export * from "./expert-market";
export * from "./experts";
export * from "./knowledge";
export * from "./library";
export * from "./plans";
export * from "./skills";
export * from "./users";
export * from "./tenants";

// `BillingPeriod` is exported by both `./plans` (strict union) and `./tenants`
// (widened with `| string`). To resolve the `export *` ambiguity we pin the
// barrel's `BillingPeriod` to the widened `./tenants` variant (a superset that
// accepts the `./plans` union). Consumers that need the strict union should
// import it from `@/lib/api/plans` directly.
export type { BillingPeriod } from "./tenants";
