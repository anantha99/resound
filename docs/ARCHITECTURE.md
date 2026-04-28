# Resound — Architecture Diagrams

Companion to [PRD-openrouter.md](PRD-openrouter.md). Three diagrams:

1. **System flow** — the full pipeline, end to end.
2. **LLM Gateway internals** — how a single classify call works, including fallbacks.
3. **Data model** — the append-only memory schema.

---

## 1. System flow

End-to-end view of one signal's journey from external source to routed notification, with config inputs and dashboard outputs.

```mermaid
flowchart TB
    %% ============ EXTERNAL SOURCES ============
    subgraph EXT["External surfaces"]
        direction LR
        REDDIT[Reddit]
        G2[G2]
        TWITTER[Twitter / X]
    end

    %% ============ CONFIG ============
    subgraph CFG["Brand config bundle (brands/&lt;brand&gt;/)"]
        direction TB
        BRAND_YAML[brand.yaml]
        SOURCES_YAML[sources.yaml]
        UNDERSTANDING_MD[understanding.md]
        ROUTING_YAML[routing.yaml]
        PEOPLE_YAML[people.yaml]
        VIEWS_YAML[views.yaml]
        MODELS_YAML[models.yaml]
    end

    %% ============ PIPELINE ============
    subgraph PIPE["Resound pipeline"]
        direction TB

        subgraph L1["Layer 1 - Ingestion"]
            REDDIT_ADAPTER[RedditSource]
            G2_ADAPTER[G2Source]
            TWITTER_ADAPTER[TwitterSource]
        end

        ORCH{{Pipeline orchestrator}}

        subgraph L2["Layer 2 - Understanding"]
            FILTER[Filter stage<br/>cheap model]
            CLASSIFY[Full classify stage<br/>premium model]
            FILTER -->|is_about_brand=true| CLASSIFY
            FILTER -->|is_about_brand=false| DROP[discard]
        end

        subgraph L3["Layer 3 - Routing"]
            RULES[RulesRouter<br/>YAML DSL]
            TIEBREAK[LLM tiebreaker<br/>when confidence&lt;0.6]
            RESOLVE[Owner resolver<br/>via people.yaml]
            RULES -->|ambiguous| TIEBREAK
            RULES -->|matched| RESOLVE
            TIEBREAK --> RESOLVE
        end

        subgraph L5["Layer 5 - Feedback"]
            FILE_FEEDBACK[FileFeedback<br/>data/routes/&lt;brand&gt;/routes.jsonl]
        end
    end

    %% ============ LLM GATEWAY ============
    subgraph GW["Cross-cutting: LLM Gateway"]
        direction TB
        OPENROUTER_GW[OpenRouterGateway<br/>OpenAI-compatible client]
        PROMPTS[Prompt templates<br/>src/resound/prompts/]
        MODELS_CONFIG[Models config loader]
        PROMPTS --> OPENROUTER_GW
        MODELS_CONFIG --> OPENROUTER_GW
    end

    %% ============ OPENROUTER ============
    OPENROUTER[("OpenRouter API<br/>openrouter.ai/api/v1")]

    subgraph PROVIDERS["Underlying providers (selected per stage)"]
        direction LR
        ANTHROPIC[Anthropic<br/>Claude]
        OPENAI[OpenAI<br/>GPT]
        GOOGLE[Google<br/>Gemini]
        META[Meta<br/>Llama]
        OTHERS[...200+ models]
    end

    %% ============ MEMORY ============
    subgraph MEM["Layer 4 - Memory (append-only)"]
        direction LR
        DB[(Postgres / Supabase<br/>or SQLite dev)]
        TABLES["signals<br/>classifications<br/>routes<br/>feedback_events<br/>outcomes<br/>llm_calls"]
        DB --- TABLES
    end

    %% ============ DASHBOARD ============
    subgraph DASH["Dashboard (Streamlit)"]
        direction LR
        LIVE[Live feed]
        BROWSER[Memory browser]
        AUDIT[Routing audit]
        TELEMETRY[LLM telemetry<br/>cost / latency / fallbacks]
    end

    %% ============ HUMANS ============
    OPERATOR((Operator))
    RECIPIENT((Recipient<br/>PM/CS/Eng))

    %% ============ FLOWS ============
    REDDIT --> REDDIT_ADAPTER
    G2 --> G2_ADAPTER
    TWITTER --> TWITTER_ADAPTER

    SOURCES_YAML -.config.-> L1
    UNDERSTANDING_MD -.context.-> L2
    ROUTING_YAML -.rules.-> RULES
    PEOPLE_YAML -.lookup.-> RESOLVE
    MODELS_YAML -.per-stage model.-> MODELS_CONFIG
    VIEWS_YAML -.dashboards.-> DASH

    REDDIT_ADAPTER --> ORCH
    G2_ADAPTER --> ORCH
    TWITTER_ADAPTER --> ORCH

    ORCH --> FILTER
    CLASSIFY --> RULES

    FILTER -.LLM call.-> GW
    CLASSIFY -.LLM call.-> GW
    TIEBREAK -.LLM call.-> GW
    BROWSER -.NL query.-> GW

    GW <--> OPENROUTER
    OPENROUTER <--> ANTHROPIC
    OPENROUTER <--> OPENAI
    OPENROUTER <--> GOOGLE
    OPENROUTER <--> META
    OPENROUTER <--> OTHERS

    ORCH ==>|record_signal| DB
    CLASSIFY ==>|record_classification| DB
    GW ==>|log llm_calls| DB
    RESOLVE ==>|record_route| DB
    RESOLVE --> FILE_FEEDBACK

    FILE_FEEDBACK --> RECIPIENT
    RECIPIENT -.marks correct=true/false.-> FILE_FEEDBACK
    FILE_FEEDBACK ==>|record_feedback| DB

    DB --> DASH
    OPERATOR -.edits.-> CFG
    OPERATOR -.views.-> DASH

    %% ============ STYLING ============
    classDef ext fill:#fde7e7,stroke:#c33,stroke-width:1px,color:#000
    classDef cfg fill:#fff4d6,stroke:#b8860b,stroke-width:1px,color:#000
    classDef pipe fill:#e7f3ff,stroke:#1e6fbf,stroke-width:1px,color:#000
    classDef gw fill:#f0e7ff,stroke:#6b3fa0,stroke-width:1px,color:#000
    classDef mem fill:#e7ffe7,stroke:#2a7a2a,stroke-width:1px,color:#000
    classDef dash fill:#ffe7f7,stroke:#a02a7a,stroke-width:1px,color:#000
    classDef human fill:#f5f5f5,stroke:#444,stroke-width:2px,color:#000

    class REDDIT,G2,TWITTER,ANTHROPIC,OPENAI,GOOGLE,META,OTHERS,OPENROUTER ext
    class BRAND_YAML,SOURCES_YAML,UNDERSTANDING_MD,ROUTING_YAML,PEOPLE_YAML,VIEWS_YAML,MODELS_YAML cfg
    class REDDIT_ADAPTER,G2_ADAPTER,TWITTER_ADAPTER,ORCH,FILTER,CLASSIFY,DROP,RULES,TIEBREAK,RESOLVE,FILE_FEEDBACK pipe
    class OPENROUTER_GW,PROMPTS,MODELS_CONFIG gw
    class DB,TABLES mem
    class LIVE,BROWSER,AUDIT,TELEMETRY dash
    class OPERATOR,RECIPIENT human
```

### How to read it

- **Red boxes** are external systems (sources + LLM providers behind OpenRouter).
- **Yellow boxes** are config files the operator edits — no code paths cross out of these.
- **Blue boxes** are pipeline layers (1, 2, 3, 5).
- **Purple box** is the LLM gateway — every dotted "LLM call" arrow into it is a place the model is decoupled from the call site.
- **Green box** is the memory layer (Postgres / Supabase / SQLite).
- **Pink box** is the dashboard.
- **Solid arrows** = data flow. **Dotted arrows** = config / prompts / observability. **Thick arrows (==>)** = writes to memory.

Notice every LLM call (filter, classify, tiebreaker, NL memory query) routes through the same gateway, and the gateway is the only thing that talks to OpenRouter. That's the swap-the-model property: change `models.yaml`, the gateway picks a different slug, no other layer notices.

---

## 2. LLM Gateway internals — one classify call

What happens inside the gateway for a single classification, including the retry/fallback chain.

```mermaid
sequenceDiagram
    autonumber
    participant C as OpenRouterClassifier
    participant GW as OpenRouterGateway
    participant CFG as models.yaml
    participant OR as OpenRouter API
    participant P1 as Primary model<br/>(claude-sonnet-4-6)
    participant P2 as Fallback 1<br/>(gpt-4.1)
    participant P3 as Fallback 2<br/>(gemini-2.5-pro)
    participant DB as llm_calls table

    C->>GW: complete(stage="classify", prompt, schema)
    GW->>CFG: lookup classify stage
    CFG-->>GW: model=claude-sonnet-4-6,<br/>fallbacks=[gpt-4.1, gemini-2.5-pro]

    GW->>OR: POST /chat/completions<br/>model=claude-sonnet-4-6<br/>response_format=json_object
    OR->>P1: route request
    P1--xOR: 503 Service Unavailable
    OR-->>GW: 503

    Note over GW: Transient error,<br/>retry with backoff (1s)
    GW->>OR: retry (attempt 2)
    OR->>P1: route request
    P1--xOR: 503
    OR-->>GW: 503

    Note over GW: Retry exhausted,<br/>move to fallback chain
    GW->>OR: POST /chat/completions<br/>model=gpt-4.1
    OR->>P2: route request
    P2-->>OR: 200 OK + JSON
    OR-->>GW: response<br/>usage={tokens, cost}

    Note over GW: Validate JSON<br/>against schema
    GW->>DB: INSERT llm_calls<br/>stage=classify<br/>model=gpt-4.1<br/>tokens, cost, latency<br/>fallback_used=true
    GW-->>C: LLMResponse(content,<br/>model_used=gpt-4.1,<br/>cost_usd, latency_ms)
```

### Key behaviors visible here

- **Single chokepoint:** the classifier never sees model slugs — it just asks for "classify stage."
- **Config-driven:** the model is resolved from `models.yaml` at call time, not at startup, so changes only need a process restart.
- **Transient vs permanent split:** 5xx and 429 retry on the same model; 4xx (other than 429) skip immediately to fallback.
- **Audit trail:** every attempt — including the failed primary — gets logged so the dashboard can show fallback rate by model.
- **Caller-observable failure mode:** if all models in the chain fail, `LLMGatewayError` is raised, the orchestrator records the signal with no classification, and the dashboard surfaces it for manual review.

---

## 3. Data model

The memory schema. Everything is append-only; nothing is ever updated except feedback acknowledgement flags.

```mermaid
erDiagram
    SIGNALS ||--|| CLASSIFICATIONS : "1:1 (when classified)"
    SIGNALS ||--o| ROUTES : "0:1 (after routing)"
    CLASSIFICATIONS ||--o| ROUTES : "0:1"
    ROUTES ||--o{ FEEDBACK_EVENTS : "many"
    ROUTES }o--o| OUTCOMES : "many:one"
    CLASSIFICATIONS ||--|{ LLM_CALLS : "1+ per classification"

    SIGNALS {
        uuid id PK
        string source
        string external_id
        string url
        string author_handle
        text content
        timestamp posted_at
        timestamp ingested_at
        jsonb raw_metadata
    }

    CLASSIFICATIONS {
        uuid id PK
        uuid signal_id FK
        bool is_about_brand
        string area
        string subarea
        string sentiment
        string severity
        string action_class
        text root_cause_hypothesis
        text summary
        float confidence
        string model_used
        int tokens_in
        int tokens_out
        decimal cost_usd
        timestamp created_at
    }

    ROUTES {
        uuid id PK
        uuid signal_id FK
        uuid classification_id FK
        string owner_id
        string destination
        jsonb rule_trace
        bool tiebreaker_used
        timestamp routed_at
    }

    FEEDBACK_EVENTS {
        uuid id PK
        uuid route_id FK
        bool correct
        bool acted_on
        text note
        timestamp recorded_at
    }

    OUTCOMES {
        uuid id PK
        text resolution_summary
        timestamp resolved_at
    }

    LLM_CALLS {
        uuid id PK
        string stage
        string model_requested
        string model_used
        string prompt_hash
        string response_hash
        int tokens_in
        int tokens_out
        decimal cost_usd
        int latency_ms
        bool fallback_used
        bool success
        timestamp called_at
    }
```

### Why this shape

- **`signals` is the immutable root.** Every later table foreign-keys to it.
- **`classifications` carries the model audit fields** (`model_used`, `tokens_in`, `tokens_out`, `cost_usd`) directly so the dashboard can attribute cost and quality without joins.
- **`llm_calls` is the granular ledger** — one row per LLM invocation, including the failed-primary attempts that triggered fallbacks. Reconciles to OpenRouter's billing dashboard within ±10%.
- **`outcomes` is many-to-one with routes** because a single ship/fix can resolve dozens of signals across sources — that's the cross-source dedup story we punted to v2.
- **No mutation paths.** The only column that changes after creation is feedback acknowledgement on `feedback_events`, and even that is recorded as a new event in v2.
