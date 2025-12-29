# ARC vs Manual Runner Setup

## Key Differences

### Manual Runner Setup (`setup_github_runner_mla_decode.sh`)

**What it does:**
- Downloads and installs GitHub Actions runner software on the server
- Configures runner with `config.sh` (creates a persistent runner instance)
- Runs `run.sh` or installs as a systemd service
- Runner runs continuously, waiting for jobs
- One runner instance = one job at a time (sequential)

**Setup steps:**
1. Run the setup script on each server
2. Runner registers with GitHub and stays online
3. GitHub sends jobs to the runner
4. Runner processes jobs sequentially

**Pros:**
- Simple setup
- Runner is always available
- No Kubernetes required

**Cons:**
- Can't scale easily (need to set up multiple runners manually)
- Sequential job execution only
- Manual management

---

### ARC Setup (What You've Done)

**What it does:**
- ARC controller manages runners as Kubernetes pods
- Runners are **ephemeral** - created on-demand when workflows need them
- Automatic scaling based on workload
- Each pod can run one job (but multiple pods = concurrent jobs)
- No manual runner installation needed

**Setup steps (already done):**
1. ✅ Install Kubernetes (k3s)
2. ✅ Install GPU device plugin
3. ✅ Install ARC controller
4. ✅ Install Runner Scale Set
5. ✅ Push workflow file to GitHub

**No additional steps needed!**

**Pros:**
- Automatic scaling (create pods as needed)
- Concurrent execution (multiple pods = multiple jobs)
- Kubernetes-native management
- No manual runner installation
- Pods are ephemeral (created/destroyed automatically)

**Cons:**
- Requires Kubernetes cluster
- More complex initial setup

---

## Do You Need the Setup Script?

**Answer: NO** ❌

With ARC:
- ✅ ARC controller is already installed
- ✅ Runner Scale Set is already configured
- ✅ Runners will be created automatically when workflows are triggered
- ✅ No need to run `setup_github_runner_mla_decode.sh`

The old setup script (`setup_github_runner_mla_decode.sh`) is for the **manual runner approach** and is **not needed** with ARC.

---

## What Happens When You Push the Workflow?

1. **Workflow file is in GitHub** ✅ (you've pushed it)
2. **When a workflow is triggered:**
   - GitHub sends job request to ARC
   - ARC controller creates an ephemeral runner pod in Kubernetes
   - Pod runs on a GPU node (thanks to Kyverno policy and node selector)
   - Pod gets exactly 1 GPU (thanks to resource limits)
   - Workflow executes in the pod
   - Pod is cleaned up when done

3. **No manual intervention needed!**

---

## Verifying ARC is Working

After pushing the workflow, you can verify:

```bash
# Check AutoscalingRunnerSet is ready
kubectl get autoscalingrunnersets -n arc-runners

# When a workflow is triggered, you should see pods being created:
kubectl get pods -n arc-runners -w

# Check listener pod (manages job requests)
kubectl get pods -n arc-runners | grep listener
```

---

## Summary

| Aspect | Manual Runner Script | ARC (Your Setup) |
|--------|---------------------|------------------|
| Runner Installation | ✅ Need to run script | ❌ Automatic (pods) |
| Runner Registration | ✅ Manual `config.sh` | ❌ Automatic (ARC) |
| Runner Management | ✅ Manual (start/stop) | ❌ Automatic (Kubernetes) |
| Scaling | ❌ Manual (multiple instances) | ✅ Automatic (pod scaling) |
| Concurrent Jobs | ❌ No (1 job per runner) | ✅ Yes (multiple pods) |
| After Push | ❌ Need to run script | ✅ Nothing needed! |

**Your workflow is ready to use - just trigger it and ARC will handle the rest!**

