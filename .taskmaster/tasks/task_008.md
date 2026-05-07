# Task ID: 8

**Title:** Integrate Memory Query into Dashboard

**Status:** pending

**Dependencies:** 6, 7

**Priority:** medium

**Description:** Add natural language search to the Memory Browser tab using the memory_query LLM stage.

**Details:**

1. Update Memory browser tab in `src/resound/dashboard/app.py`:
```python
with tab2:
    st.subheader('Memory browser')
    
    # Natural language search box
    query = st.text_input(
        'Search signals (natural language)',
        placeholder='e.g., "critical billing issues from last week"'
    )
    
    if query:
        with st.spinner('Searching...'):
            gateway = get_gateway()  # cached
            results, interpretation = memory.query_natural_language(
                brand_slug, query, gateway, limit=200
            )
        st.caption(f'Interpreted as: {interpretation}')
        if results:
            st.dataframe(pd.DataFrame(results), use_container_width=True)
        else:
            st.info('No signals match your query.')
    else:
        # Show all recent signals as before
        st.dataframe(filtered[memory_cols], use_container_width=True)
```

2. Add `@st.cache_resource` for gateway instantiation

3. Add search history/suggestions sidebar (optional enhancement)

4. Handle LLM errors gracefully with user-friendly message

**Test Strategy:**

Manual testing:
- Test 'show me all negative reviews' returns filtered results
- Test 'billing complaints this month' correctly filters by area + date
- Test empty query shows all signals
- Test LLM failure shows graceful error message
- Test search completes within 5 second target
