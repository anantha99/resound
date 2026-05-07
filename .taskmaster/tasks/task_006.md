# Task ID: 6

**Title:** Add Memory Query LLM Stage

**Status:** pending

**Dependencies:** 1 ✓, 2 ✓, 3 ✓

**Priority:** medium

**Description:** Implement free-text memory search using LLM to interpret natural language queries against the signal database.

**Details:**

1. Create `src/resound/prompts/memory_query.py`:
```python
MEMORY_QUERY_PROMPT_V1 = '''You are a memory query assistant. Convert natural language questions about customer signals into structured filters.

Available filter fields: area, subarea, sentiment, severity, action_class, source, date_range, keywords

User query: {query}

Return JSON: {
  "filters": {"area": ["product"], "severity": ["high", "critical"], ...},
  "keywords": ["word1", "word2"],
  "date_range": {"start": "2024-01-01", "end": null},
  "interpretation": "Looking for high-severity product complaints"
}'''
```

2. Add `query_natural_language()` to `SqlMemory`:
```python
def query_natural_language(
    self,
    brand_slug: str,
    query: str,
    gateway: LLMGateway,
    limit: int = 100
) -> tuple[list[dict], str]:  # (results, interpretation)
```
This method:
- Calls gateway.complete() with 'memory_query' stage
- Parses the structured filters from LLM response
- Builds SQL query with the filters
- Returns results + the LLM's interpretation string

3. Add SQL query builder method `_build_filtered_query()` that constructs SQLAlchemy query from filter dict

4. Export via gateway for dashboard use

**Test Strategy:**

Unit tests:
- Test natural language 'all complaints about billing last month' produces correct filters
- Test 'show me critical issues from Reddit' produces source + severity filters
- Test invalid/empty query returns sensible default (all recent)
- Test results returned within 5 second target
- Integration test with real signals in test database
