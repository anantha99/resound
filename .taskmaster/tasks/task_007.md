# Task ID: 7

**Title:** Add LLM Telemetry Dashboard View

**Status:** pending

**Dependencies:** 3 ✓, 4

**Priority:** medium

**Description:** Extend the Streamlit dashboard with a fourth tab showing LLM cost/latency telemetry grouped by stage and model.

**Details:**

1. Update `src/resound/dashboard/app.py` to add fourth tab 'LLM Telemetry':
```python
tab1, tab2, tab3, tab4 = st.tabs(['Live feed', 'Memory browser', 'Routing audit', 'LLM telemetry'])

with tab4:
    st.subheader('LLM Cost & Performance')
    
    # Date range selector
    col1, col2 = st.columns(2)
    start_date = col1.date_input('From', value=datetime.now() - timedelta(days=30))
    end_date = col2.date_input('To', value=datetime.now())
    
    # Cost breakdown by stage
    costs = memory.query_llm_costs(brand_slug, since=start_date)
    st.markdown('**Monthly spend by stage:**')
    cost_df = pd.DataFrame(costs)
    st.bar_chart(cost_df.pivot(index='stage', columns='model', values='total_cost'))
    
    # Cost breakdown by model
    st.markdown('**Spend by model:**')
    st.dataframe(cost_df.groupby('model')['total_cost'].sum())
    
    # Latency metrics
    latency = memory.query_llm_latency(brand_slug, since=start_date)
    st.markdown('**Latency (p50/p95) by stage:**')
    latency_df = pd.DataFrame(latency)
    st.dataframe(latency_df)
    
    # Fallback rate
    fallbacks = memory.query_fallback_rate(brand_slug, since=start_date)
    st.markdown('**Fallback trigger rate:**')
    st.metric('Primary model success rate', f"{fallbacks['primary_rate']:.1%}")
```

2. Add helper function to calculate if call used fallback model (compare model_used vs stage default)

3. Add cost reconciliation note: 'Cost tracking within ±10% of OpenRouter dashboard'

**Test Strategy:**

Manual testing:
- Verify cost charts render with sample llm_calls data
- Verify latency percentiles calculate correctly
- Verify fallback rate displays correctly
- Verify date range filter works
- Verify empty state shows helpful message
