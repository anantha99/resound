# Oatly Understanding

## What We Sell

Oatly sells oat milk and plant-based dairy alternatives through retail stores,
cafes, and foodservice channels. The Barista edition is a high-signal SKU for
coffee shops and enthusiasts.

## Voice And Positioning

Oatly mixes sustainability positioning with playful brand voice. Customer voice
often clusters around taste, cafe availability, sustainability claims, and retail
stockouts.

## Functional Area Taxonomy

- product: taste, formula, SKU quality, barista performance, packaging quality.
- ops: retail availability, cafe-channel stockouts, distribution gaps.
- marketing: sustainability claims, greenwashing skepticism, brand campaigns.
- cs: support experience, refunds, damaged orders.
- billing: subscription or order billing issues.
- engineering: ecommerce site or ordering bugs.
- other: anything that does not fit above.

## Glossary

- Barista edition: cafe-oriented SKU; stockout complaints usually route to ops.
- Greenwashing: sustainability credibility concern; route to marketing/comms.
- Minor Figures: common competitor reference in cafe stockout discussions.

## Examples

- "Three coffee shops near me switched because Oatly Barista is always out" →
  area=ops, subarea=barista_stockouts, severity=high, action_class=sprint.
- "Blackstone investment makes the sustainability ads feel fake" →
  area=marketing, subarea=sustainability_claims, severity=medium.
- "Barista edition steams perfectly" → area=product, sentiment=positive,
  action_class=fyi.
- "oat milk from another brand tastes better" with no Oatly mention →
  is_about_brand=false, action_class=ignore.

## Severity Guidance

- critical: viral health/safety allegation, mass recall, legal/regulatory risk.
- high: repeated stockouts causing cafe churn or high-reach brand trust critique.
- medium: recurring product or sustainability complaint with limited reach.
- low: isolated praise, minor complaint, or informational mention.
