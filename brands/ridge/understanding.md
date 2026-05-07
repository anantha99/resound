# Ridge — brand context for Resound

## What we sell

Minimalist wallets, rings, knives, and EDC accessories under the Ridge brand.
Sold DTC-first via ridge.com and Amazon, with growing retail distribution.
Lifetime warranty is the load-bearing brand claim — customers buy in expecting
"buy it for life" durability and price the product accordingly.

## Voice & positioning

Minimalist, premium-feeling, "buy once, cry once." Customer base skews male and
EDC-enthusiast (everyday-carry community). Ridge customers take product failure
personally — a wallet failure carries weight closer to a software service data
loss than to a snack tasting weird. Calibrate severity for durability complaints
accordingly: a single sincere "my Ridge broke" post is rarely just `low`.

## Functional area taxonomy

Use the standard Resound areas with these brand-specific subareas:

- **product**: card_ejection_mechanism, build_quality, ring_sizing, material_variants, scratching, rfid_blocking
- **engineering**: website / DTC checkout / app issues
- **billing**: ridge_subscription_billing (Ridge+), refunds, charge disputes
- **cs**: order_status, warranty_claims, ring_returns, damaged_shipment, missing_items
- **marketing**: brand campaigns, sponsorships, youtube_creator_partnerships
- **ops**: distribution_gripes, supply issues, "can't find it in my store"
- **other**: brand fandom, jokes, off-topic mentions

## Glossary of brand-specific terms

- "The Ridge" — the flagship wallet (capitalized; lowercase "the ridge" is often geological/anatomical, treat as off-brand unless other Ridge cues are present)
- "Basecamp" — knife product line; route product complaints under product, not cs
- "Buy it for life" / "lifetime guarantee" — invokes the lifetime warranty; treat as warranty_claims under cs
- "Ridge+" — subscription program; billing complaints belong under billing/ridge_subscription_billing, not generic cs

## Examples for reference

### Example 1 — Card ejection complaint (route)
> "Six months in and my Ridge won't push cards out anymore. Ejection mechanism is jammed."

Classification: is_about_brand=true, area=product, subarea=card_ejection_mechanism, severity=medium,
action_class=sprint, sentiment=negative.

### Example 2 — Warranty claim (route)
> "My Ridge wallet snapped at the screw. Pretty sure 'buy it for life' covers this — how do I claim?"

Classification: area=cs, subarea=warranty_claims, severity=medium, action_class=sprint, sentiment=neutral.
Note: "buy it for life" matches the lifetime-guarantee glossary entry — drives subarea=warranty_claims.

### Example 3 — Brand fandom (FYI, do not over-route)
> "5 years on my Ridge and it still looks new. This thing outlasts me."

Classification: area=marketing, severity=low, action_class=fyi, sentiment=positive.

### Example 4 — False positive (ignore)
> "The ridge on my Bellroy wallet is wearing down faster than I'd like."

Classification: is_about_brand=false, action_class=ignore.
Note: lowercase "the ridge" + competitor brand named in same sentence — glossary entry #1 calls this out.

## Severity guidance

- **critical** — viral PR risk, knife-product safety incident, mass warranty failure cluster, counterfeit-product mass exposure.
- **high** — repeat issue across multiple customers, warranty refused on plausible claim, churn-risk subscriber.
- **medium** — single concrete complaint that needs a response (most durability complaints land here).
- **low** — minor opinion, edge case, easily resolved via existing docs.
