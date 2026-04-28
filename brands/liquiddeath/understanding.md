# Liquid Death — brand context for Resound

## What we sell

Canned still water, sparkling water, and flavored sparkling waters under the Liquid Death brand.
Sold via DTC website, Amazon, and big-box retail (Whole Foods, Target, 7-Eleven, etc.).

## Voice & positioning

Heavy-metal aesthetic, irreverent comedy. Sustainability angle: aluminum cans over plastic.
Customers are often fans of the brand identity as much as the product itself.

## Functional area taxonomy

Use the standard Resound areas with these brand-specific subareas:

- **product**: flavor profile, can design, new SKUs, taste complaints, packaging satisfaction
- **engineering**: website / DTC checkout / app issues
- **billing**: subscription billing, refunds, charge disputes
- **cs**: order status, damaged shipments, missing items
- **marketing**: brand campaigns, sponsorships, PR
- **ops**: retail availability, distribution gaps, supply issues, "can't find it in my store"
- **other**: brand fandom, jokes, off-topic mentions

## Glossary of brand-specific terms

- "Death by the case" — bulk subscription
- "Country Club" — official fan group / loyalty program
- "Murderhead" — self-identifying superfan
- "Murder your thirst" — slogan; not a complaint indicator

## Examples for reference

### Example 1 — Genuine product complaint (route)
> "Just got my mango chainsaw 12-pack and 3 cans were dented. Disappointed."

Classification: is_about_brand=true, area=cs, subarea=damaged_shipment, severity=medium,
action_class=sprint, sentiment=negative.

### Example 2 — Retail availability (route)
> "Why can't I find liquid death anywhere in Phoenix? Every Target is out."

Classification: area=ops, subarea=retail_availability, severity=medium, action_class=sprint,
sentiment=negative.

### Example 3 — Brand fandom (FYI, do not over-route)
> "Liquid Death is the only water brand that gets me. Murder your thirst forever."

Classification: area=marketing, severity=low, action_class=fyi, sentiment=positive.

### Example 4 — False positive (ignore)
> "The new horror movie has a scene with liquid death dripping from the ceiling."

Classification: is_about_brand=false, action_class=ignore.

## Severity guidance

- **critical** — viral PR risk, food safety claim, mass complaint cluster.
- **high** — repeat issue across multiple customers, churn-risk subscriber.
- **medium** — single concrete complaint that needs a response.
- **low** — minor opinion, edge case, easily resolved via existing docs.
