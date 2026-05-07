# Task ID: 10

**Title:** Add CLI Model Testing Command

**Status:** pending

**Dependencies:** 1 ✓, 2 ✓

**Priority:** low

**Description:** Add `resound models test --stage classify` command to verify model configuration and test prompts.

**Details:**

1. Add `models` command group to `src/resound/cli.py`:
```python
@app.command()
def models_test(
    stage: str = typer.Option('classify', help='Stage to test: filter, classify, routing_tiebreaker, memory_query'),
    brand: str = typer.Option('liquiddeath', help='Brand slug for context'),
) -> None:
    '''Test a model configuration by running a sample prompt.'''
    cfg = load_brand_config(brand)
    gateway = OpenRouterGateway(cfg)
    
    sample_prompts = {
        'filter': 'Is this about Liquid Death? "I love drinking water"',
        'classify': 'Classify: "The cans are dented when delivered"',
        'routing_tiebreaker': 'Route: billing complaint, high severity',
        'memory_query': 'Find all negative reviews from last week',
    }
    
    console.print(f'Testing stage: {stage}')
    console.print(f'Model: {gateway.get_model_for_stage(stage)}')
    
    response = gateway.complete(stage=stage, prompt=sample_prompts[stage])
    
    console.print(f'Response: {response.content}')
    console.print(f'Tokens: {response.tokens_in} in, {response.tokens_out} out')
    console.print(f'Cost: ${response.cost_usd:.4f}')
    console.print(f'Latency: {response.latency_ms}ms')
```

2. Add `resound models list` command to show current model configuration:
```python
@app.command()
def models_list(brand: str = typer.Option(None)):
    '''Show model configuration for each stage.'''
    # Print table of stage -> model -> fallbacks
```

3. Add `resound models switch --stage classify --model openai/gpt-4.1` for quick switching (updates models.yaml)

**Test Strategy:**

Manual testing:
- Test `resound models test --stage classify` returns valid response
- Test `resound models list` shows all configured stages
- Test with invalid stage name shows helpful error
- Test with missing API key shows clear error message
