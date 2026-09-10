# Progressive rollouts

Progressive rollouts automate traffic promotion across structured stages while verifying application stability at each step.

## Scenario definition

Scenarios are defined in YAML files. Each scenario lists traffic percentages and soak intervals:

```yaml
name: progressive-rollout
description: Gradual canary rollout with staged soak intervals
steps:
  - weight: 5.0
    duration_seconds: 60
  - weight: 25.0
    duration_seconds: 120
  - weight: 50.0
    duration_seconds: 300
  - weight: 100.0
    duration_seconds: 0
```

Optionally, scenarios can override global SLA thresholds:

```yaml
sla:
  max_error_rate_percent: 0.5
  max_p99_latency_ms: 200.0
  min_sample_size: 20
```

## Execution lifecycle

1. **Start**: The engine applies the first step's weight and begins the soak timer.
2. **Soak**: The engine holds the current weight for `duration_seconds`. Every 500 milliseconds, it checks whether the rollback guard has tripped.
3. **Advance**: If the soak timer expires without incident, the engine moves to the next step.
4. **Completion**: When the final step reaches 100% traffic, the engine marks the scenario as `COMPLETED`.

## Abort handling

If the rollback guard trips during any stage of the rollout, the rollout engine cancels the scenario immediately and sets its state to `ABORTED`. Canary traffic reverts to 0%, and subsequent steps are skipped.
