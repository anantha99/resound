# Liquid Death — brand context for Resound

## What we sell

Canned beverages under the Liquid Death brand. Heavy-metal aesthetic and
intentionally parodic product names. Sold via DTC website (liquiddeath.com),
Amazon, and big-box retail (Whole Foods, Target, 7-Eleven, etc.).

### Product catalog

The classifier MUST treat the following names as Liquid Death products,
even when they sound like jokes, references to other brands, or
horror-movie titles. Most are deliberately parodic.

**This list is not exhaustive.** Liquid Death frequently launches
limited-edition, regional, and seasonal flavors with parody names
(e.g., "Deathberry Inferno Tree", "Convicted Melon", "Cereal Criminal")
that may not appear here. **For posts on r/LiquidDeath specifically**
(the brand's official subreddit), default to `is_about_brand=true`
unless the content is obviously off-topic (politics, unrelated fan
fiction, etc.). A post in r/LiquidDeath reviewing a flavor with a
heavy-metal-style name is almost always a real LD product, even if
the name isn't on this catalog.

**Mountain Water (still water):**
- "Mountain Water" — flagship plain still water in a tallboy can

**Sparkling water:**
- Severed Lime
- Mango Chainsaw
- Convicted Melon
- Berry It Alive
- Cherry Obituary
- Killbert Grape (2026 release)
- Sinister Ginger (2026 release)
- "Mtn Don't" / "Mt. Death" — Mountain Dew–style parody flavor (2026 release)

**Iced tea:**
- Dead Billionaire — black tea + lemonade. **Originally launched as "Armless Palmer"** (an Arnold Palmer parody) in 2023; renamed after Arnold Palmer's estate threatened legal action. Either name is a real LD product reference.
- Grim Leafer — black tea
- Pop-Tarts Carnage — strawberry-Pop-Tart-flavored iced tea (collab with Pop-Tarts, 2026)

**Energy drinks** (launched January 2026, 200mg caffeine):
- Tropical Terror
- Murder Mystery
- Orange Horror
- Scary Strawberry

### Collaborations (limited edition / merch)

These are real LD products and posts about them are brand-relevant:

- **e.l.f. Cosmetics** — Corpse Paint makeup kit (2024) and Lip Embalms collection with character "Glothar"
- **Pit Viper** — limited-edition sunglasses ("shades for the dead")
- **Pop-Tarts** — Carnage iced tea (see above)
- **Fruity Pebbles** — "Cereal Criminal" cereal-milk-flavored sparkling water (July 2025)

## Voice & positioning

Heavy-metal aesthetic, irreverent comedy. Sustainability angle: aluminum
cans over plastic. Customers are often fans of the brand identity as
much as the product itself, and frequently use ironic / sarcastic praise
("this water made me kill god", "I'd murder my own grandmother for a
case of this") that is almost always **positive sentiment**, not actual
threats.

## Functional area taxonomy

Use the standard Resound areas with these brand-specific subareas:

- **product**: flavor profile, can design, new SKUs, taste complaints, packaging satisfaction, formulation changes (sugar/caffeine/sweetener)
- **engineering**: website / DTC checkout / app / liquiddeath.com issues ONLY. **Not Amazon, not retail-partner systems.**
- **billing**: subscription billing, refunds, charge disputes (DTC subscriptions only)
- **cs**: order status, damaged shipments, missing items, Amazon delivery problems, retail-partner fulfillment failures
- **marketing**: brand campaigns, sponsorships, PR, collab launches, viral moments
- **ops**: retail availability, distribution gaps, supply issues, "can't find it in my store", Amazon stock-outs
- **legal**: trademark / IP disputes, name changes forced by lawsuit threats (see Armless Palmer history)
- **other**: brand fandom, jokes, off-topic mentions

### Disambiguation: Amazon vs. liquiddeath.com

If the customer's complaint is about **Amazon** (missing packs, cancelled orders, items out of stock there, subscription failures on Amazon), the area is **`cs`** (delivery/fulfillment failure) or **`ops`** (Amazon stock-outs) — **never `engineering`**. Engineering is reserved for issues with our own DTC site/app/checkout.

## Glossary of brand-specific terms

- "Death by the case" — bulk subscription
- "Country Club" — official fan group / loyalty program
- "Murderhead" — self-identifying superfan
- "Murder your thirst" — slogan; not a complaint indicator
- "Glothar" — character associated with the e.l.f. Lip Embalms collab
- "Armless Palmer" — original name of the Dead Billionaire iced tea; renamed under legal pressure. References to "armless palmer lawsuit" or "armless palmer x2" are about LD's legal/PR history.

## Examples for reference

### Example 1 — Genuine product complaint (route)
> "Just got my mango chainsaw 12-pack and 3 cans were dented. Disappointed."

Classification: is_about_brand=true, area=cs, subarea=damaged_shipment,
severity=medium, action_class=sprint, sentiment=negative.

### Example 2 — Retail availability (route)
> "Why can't I find liquid death anywhere in Phoenix? Every Target is out."

Classification: area=ops, subarea=retail_availability, severity=medium,
action_class=sprint, sentiment=negative.

### Example 3 — Brand fandom (FYI, do not over-route)
> "Liquid Death is the only water brand that gets me. Murder your thirst forever."

Classification: area=marketing, severity=low, action_class=fyi,
sentiment=positive.

### Example 4 — False positive (ignore)
> "The new horror movie has a scene with liquid death dripping from the ceiling."

Classification: is_about_brand=false, action_class=ignore.

### Example 5 — Parody-product mention (route, NOT ignore)
> "They're finally selling 12 packs of Mtn Don't (Now Mt. Death)!"

"Mt. Death" / "Mtn Don't" is a Liquid Death sparkling water flavor.
Classification: is_about_brand=true, area=ops, subarea=retail_availability,
severity=low, action_class=fyi, sentiment=positive.

### Example 6 — Legal/PR history reference (route, NOT ignore)
> "How long until armless palmer lawsuit x2"

References LD's history of legally borderline parody names (Armless Palmer
→ Dead Billionaire). Brand-relevant chatter about marketing/legal strategy.
Classification: is_about_brand=true, area=legal, severity=low,
action_class=fyi, sentiment=neutral.

### Example 7 — Collab product mention (route)
> "The Pop-Tart Carnage tasting notes: smell 9/10, flavor 8/10."

Classification: is_about_brand=true, area=product, subarea=flavor_profile,
severity=low, action_class=fyi, sentiment=positive.

### Example 8 — Ironic praise (route as positive, NOT negative)
> "This Severed Lime made me kill god. 10/10 would murder again."

Sarcastic LD-fandom voice. Classification: is_about_brand=true, area=marketing,
sentiment=positive (NOT negative — the violent imagery is brand-on-voice fandom).

## Severity guidance

- **critical** — viral PR risk, food safety claim, mass complaint cluster.
- **high** — repeat issue across multiple customers, **OR explicit churn-risk language from a single customer** ("considering switching brands", "this is the last time I buy from them", "deleting my subscription", "going back to [competitor]"). One customer threatening to leave = high.
- **medium** — single concrete complaint that needs a response but no churn signal.
- **low** — minor opinion, edge case, easily resolved via existing docs.

**Churn-language examples (escalate to high severity):**
- "I'm considering switching to [other brand]"
- "They changed my favorite, I might just stop buying"
- "This is enough for me to cancel my subscription"
- "Going back to [competitor] until they fix this"
