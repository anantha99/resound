# Task ID: 13

**Title:** Add Classification Fields for Audit Trail

**Status:** pending

**Dependencies:** 1 ✓, 3 ✓

**Priority:** medium

**Description:** Extend Classification model and database schema to store model_used, tokens_in, tokens_out, and cost_usd per classification.

**Details:**

1. Update `Classification` model in `src/resound/models.py`:
```python
class Classification(BaseModel):
    # ... existing fields ...
    model_used: Optional[str] = None  # OpenRouter model slug
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None
```

2. Update `ClassificationRow` in `src/resound/memory/__init__.py`:
```python
model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
```

3. Update `record_classification()` to persist new fields

4. Update classifiers to populate these fields from LLMResponse

5. Update dashboard to show model_used in signal detail view

6. Create Alembic migration for schema changes

**Test Strategy:**

Unit tests:
- Test Classification model accepts new optional fields
- Test record_classification persists all fields
- Test query_recent returns model_used, tokens, cost
- Test migration applies cleanly to existing database
- Test backward compatibility with existing classifications (null values ok)
