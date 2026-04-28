# Fulfil — brand context for Resound

## What we sell

Fulfil is a modern ERP designed specifically for high-growth eCommerce and wholesale merchants. Unlike generic ERPs (NetSuite, Brightpearl, Cin7), Fulfil is built for commerce from day one — bundles, subscriptions with deferred revenue, multi-warehouse allocation, and native Shopify / Amazon / 3PL integrations are core features, not customizations.

Our customers are DTC brands like Ridge, HexClad, Mejuri, Grüns, EndySleep — typically doing $5M+ in annual revenue on Shopify with complex operational needs (multi-channel, multi-warehouse, subscriptions, wholesale alongside DTC).

## Voice & positioning

Direct, opinionated, anti-bloat. We pitch against NetSuite by emphasizing fixed-price implementation (8–12 weeks vs. 6–12 months), no surprise consultant bills, and AI-native features (Claude integration, MCP, AI-powered SQL report generation, agentic workflows for support and docs).

Bootstrapped, profitable, ~$7M ARR, ~50 employees. Distributed team with hubs in San Francisco, Bengaluru, Toronto, and Miami.

## Functional area taxonomy

Use the standard Resound areas with these Fulfil-specific subareas:

- **product**: feature requests, UX feedback, missing capabilities. Subareas:
  - `bundles` — bundle accounting, BOM, kit allocation
  - `inventory` — counts, reservations, multi-warehouse
  - `orders` — order management, OMS workflows
  - `wholesale` — B2B order workflows, EDI
  - `manufacturing` — production runs, work orders
  - `financials` — accounting, deferred revenue, multi-currency
  - `reporting` — custom reports, BigQuery, AI-SQL
  - `wms` — pick / pack / ship workflows, scanning

- **engineering**: bugs, performance, integration breakages. Subareas:
  - `shopify_integration`, `amazon_integration`, `3pl_integration`
  - `api`, `webhooks`, `data_warehouse`
  - `mcp`, `claude_integration` (the AI surface)
  - `performance`, `outage`

- **billing**: pricing complaints, contract issues, renewal pushback.

- **cs** (customer success): implementation help, configuration questions, training.

- **marketing**: how Fulfil is perceived publicly, website / messaging feedback, competitor mentions.

- **ops**: GTM operations, sales process feedback, onboarding friction.

- **other**: brand mentions in unrelated discussions.

## Glossary of brand-specific terms

- "Bundle" — a SKU made of multiple component SKUs. Critical Fulfil differentiator.
- "Allocation" — assigning inventory to orders across warehouses.
- "3PL integration" — third-party logistics integration. Fulfil supports 400+.
- "BOM" — bill of materials, used in manufacturing flows.
- "OMS" — order management system. Fulfil includes OMS as a module.
- "WMS" — warehouse management system. Fulfil includes WMS as a module.
- "Helpdesk PR agent" — internal tooling: agent that watches closed tickets and opens doc PRs (referenced in ST's LinkedIn posts).
- "MCP" — Model Context Protocol. Fulfil ships an MCP server for Claude integration; this is a competitive moat.
- "Fixed-price implementation" — Fulfil's positioning: 8–12 week go-live, single quote, no surprise consultant bills.
- "Fulfillian" — Fulfil employee.

## Examples for reference

### Example 1 — Engineering bug, sprint priority (route to engineering)
> "Multi-warehouse allocation logic doesn't account for freight class on heavier SKUs. We've had to manually re-route orders for two months."

Classification: is_about_brand=true, area=engineering, subarea=performance, severity=high, action_class=sprint, sentiment=negative. Routes to the WMS / commerce-core engineering owner.

### Example 2 — Product roadmap input (route to product)
> "The new AI-powered SQL report generation has been incredible. I can build reports in minutes that used to take significant time."

Classification: area=product, subarea=reporting, severity=low, action_class=fyi, sentiment=positive. Routes to product PM as positive feedback / FYI.

### Example 3 — Competitive comparison (FYI to GTM/marketing)
> "Evaluated Fulfil vs. NetSuite. Fulfil's bundle handling out of the box was the deciding factor."

Classification: area=marketing, severity=low, action_class=fyi, sentiment=positive. Routes to GTM team.

### Example 4 — Implementation friction (route to CS)
> "Onboarding to Fulfil took longer than the 10 weeks promised. Configuration of our wholesale workflows kept hitting edge cases."

Classification: area=cs, subarea=implementation, severity=medium, action_class=sprint, sentiment=mixed. Routes to merchant success / implementations lead.

### Example 5 — False positive (ignore)
> "I need to fulfil my new year's resolution to learn Spanish."

Classification: is_about_brand=false, action_class=ignore.

### Example 6 — Critical PR risk
> "Fulfil ERP outage took down our entire Shopify checkout for 3 hours during BFCM. Lost hundreds of thousands in sales."

Classification: area=engineering, subarea=outage, severity=critical, action_class=immediate, sentiment=negative. Routes to exec + engineering leadership immediately.

## Severity guidance

- **critical** — outages, security incidents, viral PR risk, churn-imminent merchants, multi-merchant complaint clusters.
- **high** — repeat issue across multiple customers, blocking workflow for a single large merchant, public criticism from a known brand.
- **medium** — single concrete complaint that needs a response, feature request with broad applicability.
- **low** — minor opinion, edge case, easily resolved via existing docs (this is exactly the doc-PR-agent territory ST has already automated).
