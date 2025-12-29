# GPU Kyverno Policy - Known Limitation and Workaround

## Problem

We need to inject GPU resources into workflow pods (ending with `-workflow`) but NOT into runner pods. However, Kyverno's current pattern matching capabilities are limited:

1. **Preconditions don't support pattern matching**:
   - No `EndsWith` operator
   - `contains()` JMESPath doesn't work reliably
   - `AnyIn` requires exact matches, not patterns

2. **Exclude blocks don't support wildcard patterns** reliably:
   - Wildcards in `names` field don't work as expected
   - Cannot exclude based on name patterns

3. **CEL preconditions** may not be available in all Kyverno versions

## Current Workaround

The policy currently applies to ALL pods in `arc-runners` namespace. This means:
- ✅ Workflow pods get GPU (needed)
- ❌ Runner pods also get GPU (not needed, causes conflicts)

**Impact**: With only 1 GPU available, runner pods will claim the GPU, and workflow pods will fail with "Available: 0" errors.

## Potential Solutions (Requiring Changes)

### Option 1: Use Labels (Best Solution)
If ARC could be configured to set a label on workflow pods (e.g., `arc.github.com/pod-type: workflow`), we could use:
```yaml
preconditions:
  all:
  - key: "{{request.object.metadata.labels.arc\.github\.com/pod-type}}"
    operator: Equals
    value: "workflow"
```

**Action Required**: Check if ARC supports setting labels on workflow pods, or file a feature request.

### Option 2: Separate Namespaces
Put runner pods and workflow pods in different namespaces:
- `arc-runners`: Runner pods only (no GPU policy)
- `arc-workflows`: Workflow pods only (with GPU policy)

**Action Required**: Configure ARC to create workflow pods in a different namespace (may require ARC changes).

### Option 3: Multiple GPUs
If you have multiple GPUs, configure the policy to allow sharing:
- Remove the 1 GPU limit
- Allow multiple pods to share GPUs (may cause performance issues)

**Not Recommended**: GPU sharing is not supported in Kubernetes.

### Option 4: Wait for Kyverno Enhancement
Kyverno may add better pattern matching support in future versions.

## Current Policy Status

The policy file `amd-gpu-kyverno-policy.yaml` currently applies to all pods due to these limitations. It will need to be updated once one of the solutions above is implemented.


