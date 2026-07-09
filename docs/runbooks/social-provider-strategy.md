# Social Provider Strategy

Last updated: 2026-07-09

This note captures the provider strategy for Resound's public-listening and brand-context work. Fast implementation should keep public observation, owned-account analytics, and brand enrichment as separate ingestion lanes.

## Recommendation

Use Apify as the default provider for public social listening. Use official platform APIs only when Resound needs owned-account truth, permissioned analytics, write actions, private surfaces, or compliance-sensitive access. Use Context.dev for onboarding and brand context, not as a replacement social feed.

| Lane | Provider | Resound Use |
| --- | --- | --- |
| Public social chatter | Apify plus selected public APIs | Create raw signals for classification and routing. |
| Owned-channel analytics | Official platform APIs | Pull authenticated reach, impressions, retention, audience, ads, and moderation data. |
| Brand context | Context.dev | Enrich brand setup with logos, colors, socials, website content, docs, and structured brand facts. |

## Provider Boundaries

### Apify

Apify is a good fit when the desired data is publicly visible in a browser and Resound needs breadth across platforms quickly.

Use it for:

- Public posts, captions, descriptions, URLs, timestamps, and authors.
- Public comments and replies where reachable.
- Public engagement counts such as likes, views, shares, replies, comments, reposts, and retweets.
- Public profile, page, channel, subreddit, hashtag, place, and list metadata.
- Keyword, hashtag, profile, subreddit, and URL discovery.
- Public media metadata such as images, thumbnails, video URLs, sounds, and transcripts when exposed.
- Public ad-library or transparency-style creative data when covered by a maintained actor.

Do not treat Apify as source of truth for:

- Owned-account analytics such as reach, impressions, watch time, saves, profile visits, retention, and audience demographics.
- Paid-media metrics such as spend, CPM, CPC, CTR, conversion events, targeting, and attribution.
- Private or permissioned surfaces such as DMs, private groups, hidden comments, or logged-in-only data.
- Write actions such as posting, replying, deleting, hiding, moderating, following, or marking resolved.
- Compliance-grade deletion handling, auditability, stable enterprise access, or full-fidelity historical archives.

### Official Platform APIs

Official APIs should be added when a customer connects an owned account or when production guarantees require permissioned access.

Use them for:

- OAuth-backed customer account connections.
- Owned social/page/channel analytics.
- Ads and campaign reporting.
- Moderation, publishing, inbox, and comment-management workflows.
- Webhooks or streams where polling is not good enough.
- Compliance, deletion events, and licensed historical data where required.

### Context.dev

Context.dev is useful for the setup and enrichment side of Resound.

Use it for:

- Brand onboarding from a domain, email, or brand name.
- Discovering official social handles and website links.
- Logos, colors, descriptions, industry, address, and other brand profile fields.
- Crawling help docs, FAQs, pricing pages, changelogs, and product docs into clean Markdown.
- Structured extraction into schema-shaped brand context.
- Enriching linked pages before signal classification.

Do not use it as the primary source for social conversation ingestion.

## Platform Matrix

| Platform | Apify/Public Lane | Official API Lane |
| --- | --- | --- |
| Reddit | Public posts, comments, users, subreddits, search, and comment trees. | Authenticated user/mod actions, private messages, compliance-sensitive Reddit Data API use. |
| X/Twitter | Public search, profiles, posts, mentions, and observed engagement counts. | Recent or full-archive search guarantees, filtered streams, compliance, account actions, paid/enterprise access. |
| Instagram | Public posts, reels, profiles, hashtags, tagged posts, comments, and visible metrics. | Business/Creator insights, mentions/webhooks, publishing, comment moderation, audience metrics. |
| Facebook | Public page posts, public comments/reactions, page metadata, ad-library-style data. | Page insights, owned comments/moderation, Messenger, Marketing API ads/reporting. |
| TikTok | Public videos, hashtags, profiles, comments, sounds, and visible metrics. | Business/ads APIs, posting APIs, official research/compliance access, owned analytics. |
| YouTube | Public videos, channels, comments, search, and public counts. | YouTube Analytics API for retention, subscribers, geography, revenue, traffic sources, and owned-channel metrics. |
| LinkedIn | Public post/profile/company scraping where allowed and stable enough. | Organization posts/comments, page access, ads reporting, professional demographics through LinkedIn Marketing APIs. |
| Pinterest | Public pins, boards, search, and visible profile data where available. | Owned pins/boards, analytics, ads, and account-scoped data. |

## Data Model Implications

Keep provider provenance explicit on ingested records and projections.

Suggested dimensions:

- `source_provider`: `apify`, `official`, `context_dev`, or a licensed vendor name.
- `access_type`: `public`, `owned`, or `licensed`.
- `metric_type`: `observed_public`, `owner_analytics`, `paid_media`, or `brand_context`.
- `external_source`: platform name such as `reddit`, `instagram`, `youtube`, or `x`.

This prevents public-scraped counts from being confused with authenticated owner analytics, and it keeps future official connectors from needing to unwind the Apify integration.

## Implementation Sequence

1. Keep the current Apify public-listening path as the v1 ingestion engine.
2. Validate additional Apify sources one at a time, starting with the platforms that matter for demos.
3. Add Context.dev to onboarding so approved setup can populate brand context, discover handles, and seed listening profiles.
4. Add official owned-account connectors only after a clear customer need for analytics, ads, moderation, publishing, or private/account-scoped data.
5. Keep paid-social reporting separate from organic customer signals until the product explicitly needs a combined view.

## Product Decision To Revisit

The main unresolved product choice is whether Resound v1 is strictly a public listening and routing engine, or whether the pitch should include owned-channel analytics. The current backend and demo path are aligned with public listening first.
