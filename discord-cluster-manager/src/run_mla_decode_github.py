#!/usr/bin/env python3
"""
Helper script to run the mla-decode task on GitHub Actions runner directly,
using the task definition in `mla-decode/task.yml`.

Usage (from project root):
    uv run python src/run_mla_decode_github.py --submission path/to/submission.py

You must:
  1. Have a GitHub token set in environment variable GITHUB_TOKEN
  2. Have GITHUB_REPO set (e.g., "owner/repo")
  3. Have ARC (Actions Runner Controller) set up with runner label amd-arc-runner
  4. Have the Docker image published (ghcr.io/leoxinhaolee/amd-runner:latest)
"""

import argparse
import asyncio
import base64
import dataclasses
import datetime
import json
import os
import uuid
import zlib
from pathlib import Path
from typing import Optional

from libkernelbot.consts import AMD_REQUIREMENTS, GitHubGPU, SubmissionMode
from libkernelbot.launchers.github import GitHubRun, patched_create_dispatch
from libkernelbot.report import RunProgressReporter
from libkernelbot.run_eval import (
    CompileResult,
    EvalResult,
    FullResult,
    ProfileResult,
    RunResult,
    SystemInfo,
)
from libkernelbot.submission import compute_score
from libkernelbot.task import LeaderboardTask, build_task_config, make_task_definition


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MLA_DECODE_TASK_YAML = PROJECT_ROOT / "src" / "mla-decode" / "task.yml"


class SimpleReporter(RunProgressReporter):
    """Minimal reporter that prints to console."""

    async def _update_message(self):
        print(f"[{self.title}]")
        for line in self.lines:
            print(f"  {line}")

    async def display_report(self, title: str, report):
        print(f"\n=== {title} ===")
        print(f"Report has {len(report.data)} items")


def load_mla_decode_task() -> LeaderboardTask:
    """Load the mla-decode LeaderboardTask from its YAML definition."""
    if not MLA_DECODE_TASK_YAML.exists():
        raise FileNotFoundError(
            f"Could not find mla-decode task definition at {MLA_DECODE_TASK_YAML}. "
            "Run this script from the project root."
        )
    definition = make_task_definition(MLA_DECODE_TASK_YAML)
    return definition.task


async def run_mla_decode_on_github(
    submission_code: str,
    gpu_type: str = "MI300",
    mode: str = "leaderboard",
    github_repo: Optional[str] = None,
    github_token: Optional[str] = None,
    github_branch: Optional[str] = None,
    runner_name: Optional[str] = None,
    workflow_file: Optional[str] = None,
) -> tuple[FullResult, LeaderboardTask]:
    """
    Run an mla-decode submission on GitHub Actions using the official task definition.

    Args:
        submission_code: Contents of the user's `submission.py`
        gpu_type: One of GitHubGPU names (MI300, MI250, MI300x8)
        mode: One of: test, benchmark, leaderboard, profile, private
        github_repo: GitHub repository (owner/repo). If None, uses GITHUB_REPO env var.
        github_token: GitHub token. If None, uses GITHUB_TOKEN env var.
        github_branch: GitHub branch. If None, uses GITHUB_WORKFLOW_BRANCH env var or 'main'.
        runner_name: GitHub Actions runner label (e.g., 'amd-arc-runner' or 'amd-docker'). 
                     If None, defaults to 'amd-arc-runner' based on GPU type.
        workflow_file: Workflow file path (e.g., 'amd-mla-decode-workflow-ARC.yml' or 
                       '.github/workflows/amd-mla-decode-workflow.yml'). If None, defaults to 
                       '.github/workflows/amd-mla-decode-workflow-ARC.yml'.
    """
    # Load task from mla-decode/task.yml
    task = load_mla_decode_task()

    # Map CLI mode to SubmissionMode enum
    try:
        mode_enum = SubmissionMode(mode)
    except ValueError as e:
        valid = ", ".join(m.value for m in SubmissionMode)
        raise ValueError(f"Invalid mode '{mode}'. Valid modes: {valid}") from e

    # Get GitHub configuration
    repo = github_repo or os.getenv("GITHUB_REPO")
    if not repo:
        raise ValueError(
            "GITHUB_REPO environment variable not set. "
            "Set it or pass --github-repo argument."
        )

    token = github_token or os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_TOKEN environment variable not set. "
            "Set it or pass --github-token argument."
        )

    branch = github_branch or os.getenv("GITHUB_WORKFLOW_BRANCH", "main")

    # Validate GPU type
    try:
        gpu_enum = GitHubGPU[gpu_type.upper()]
    except KeyError:
        valid = ", ".join(g.name for g in GitHubGPU)
        raise ValueError(f"Invalid GPU type '{gpu_type}'. Valid types: {valid}")

    # Build config using the same path as the backend
    config = build_task_config(
        task=task,
        submission_content=submission_code,
        arch=None,  # Python task – arch unused
        mode=mode_enum,
    )

    if runner_name is None:
        # Default to ARC runner, but can be overridden via parameter
        runner_name_map = {
            "MI300": "amd-arc-runner",
            "MI250": "amd-arc-runner",  # Adjust if you have a different runner for MI250
            "MI300x8": "amd-arc-runner",  # Adjust if you have a different runner for MI300x8
        }
        runner_name = runner_name_map.get(gpu_type.upper(), "amd-arc-runner")

    reporter = SimpleReporter(f"mla-decode on {gpu_enum.name} (GitHub Actions)")

    print(f"Submitting mla-decode task to GitHub Actions on {gpu_enum.name} with mode='{mode_enum.value}'...")

    # Prepare payload
    payload = base64.b64encode(zlib.compress(json.dumps(config).encode("utf-8"))).decode("utf-8")

    inputs = {
        "payload": payload,
        "runner": runner_name,
        "requirements": AMD_REQUIREMENTS,
    }

    # Determine workflow file (if not explicitly provided)
    if workflow_file is None:
        # Default to ARC workflow, but can be overridden via parameter
        workflow_file = ".github/workflows/amd-mla-decode-workflow-ARC.yml"
    elif not workflow_file.startswith(".github/workflows/"):
        # If user provided just filename, prepend the path
        workflow_file = f".github/workflows/{workflow_file}"
    run_id = str(uuid.uuid4())
    inputs_with_run_id = {**inputs, "run_id": run_id}
    
    # Use the GitHub API directly to trigger the workflow
    from github import Github
    gh = Github(token)
    github_repo_obj = gh.get_repo(repo)
    
    workflow = await asyncio.to_thread(github_repo_obj.get_workflow, workflow_file)
    print(f"✓ Found workflow using path: {workflow_file}")
    assert workflow is not None, f"Workflow '{workflow_file}' not found in repository '{repo}'"
    
    # Trigger it
    success = await asyncio.to_thread(
        patched_create_dispatch, workflow, branch, inputs=inputs_with_run_id
    )
    
    if not success:
        raise RuntimeError("Failed to trigger GitHub Action workflow.")
    
    await reporter.push("⏳ Waiting for workflow to start...")
    
    # Wait for the run to appear
    await asyncio.sleep(10)
    trigger_time = datetime.datetime.now(datetime.timezone.utc)
    expected_run_name = f"AMD MLA-Decode Job - {run_id}"
    
    # Find the run
    recent_runs_paginated = await asyncio.to_thread(
        workflow.get_runs, event="workflow_dispatch"
    )
    
    found_run = None
    runs_checked = 0
    try:
        run_iterator = recent_runs_paginated.__iter__()
        while runs_checked < 100:
            try:
                run_obj = next(run_iterator)
                runs_checked += 1
                if (run_obj.name == expected_run_name and 
                    run_obj.created_at.replace(tzinfo=datetime.timezone.utc) > 
                    trigger_time - datetime.timedelta(seconds=30)):
                    found_run = run_obj
                    break
            except StopIteration:
                break
    except Exception as e:
        raise RuntimeError(f"Error finding workflow run: {e}") from e
    
    if not found_run:
        raise RuntimeError(f"Could not find workflow run with name '{expected_run_name}'")
    
    # Create GitHubRun instance and set the found run
    run = GitHubRun(repo, token, branch, workflow_file)
    run.run = found_run
    
    # Wait for completion with callback
    async def status_callback(gh_run):
        status = gh_run.status
        elapsed = gh_run.elapsed_time
        if elapsed:
            elapsed_str = f"{elapsed.total_seconds():.0f}s"
        else:
            elapsed_str = "unknown"
        url = gh_run.html_url or "N/A"
        await reporter.push(f"⏳ Status: {status} (elapsed: {elapsed_str}) | {url}")

    # Get timeout from config
    timeout_map = {
        SubmissionMode.TEST.value: config.get("test_timeout", 900),
        SubmissionMode.BENCHMARK.value: config.get("benchmark_timeout", 900),
        SubmissionMode.LEADERBOARD.value: config.get("ranked_timeout", 1200),
    }
    timeout_seconds = timeout_map.get(mode_enum.value, 1800)
    timeout_minutes = (timeout_seconds // 60) + 5  # Add buffer

    try:
        await run.wait_for_completion(status_callback, timeout_minutes=timeout_minutes)
    except TimeoutError as e:
        raise RuntimeError(f"Workflow timed out after {timeout_minutes} minutes") from e

    await reporter.push("Downloading artifacts...")
    
    # Check workflow run status first
    run_status = run.status
    run_conclusion = getattr(run.run, 'conclusion', None) if run.run else None
    if run_status != "completed":
        raise RuntimeError(
            f"Workflow did not complete. Status: {run_status}. "
            f"Check the workflow run at: {run.html_url}"
        )
    if run_conclusion and run_conclusion != "success":
        raise RuntimeError(
            f"Workflow completed with failure. Conclusion: {run_conclusion}. "
            f"Check the workflow run at: {run.html_url}"
        )
    
    # Get artifacts
    artifacts = run.get_artifact_index()
    
    # List available artifacts for debugging
    if not artifacts:
        raise RuntimeError(
            f"No artifacts found in workflow run. "
            f"Workflow may have failed before creating artifacts. "
            f"Check the workflow run at: {run.html_url}"
        )
    
    await reporter.push(f"Found {len(artifacts)} artifact(s): {', '.join(artifacts.keys())}")

    # Download result.json
    if "run-result" not in artifacts:
        available = ", ".join(artifacts.keys()) if artifacts else "none"
        raise RuntimeError(
            f"Missing 'run-result' artifact from workflow run. "
            f"Available artifacts: {available}. "
            f"Check the workflow run at: {run.html_url}"
        )

    result_artifact = artifacts["run-result"]
    artifact_data = await run.download_artifact(result_artifact)

    # Parse result.json
    if "result.json" not in artifact_data:
        raise RuntimeError("Missing result.json in run-result artifact")

    result_dict = json.loads(artifact_data["result.json"].decode("utf-8"))

    # Convert to FullResult (replicating logic from GitHubLauncher.run_submission)
    runs = {}
    for k, v in result_dict["runs"].items():
        comp_res = None if v.get("compilation") is None else CompileResult(**v["compilation"])
        run_res = None if v.get("run") is None else RunResult(**v["run"])
        profile_res = None if v.get("profile") is None else ProfileResult(**v["profile"])

        # Update profile artifact to the actual download URL
        if profile_res is not None and "profile-data" in artifacts:
            profile_res.download_url = artifacts["profile-data"].public_download_url

        res = EvalResult(
            start=datetime.datetime.fromisoformat(v["start"]),
            end=datetime.datetime.fromisoformat(v["end"]),
            compilation=comp_res,
            run=run_res,
            profile=profile_res,
        )
        runs[k] = res

    system = SystemInfo(**result_dict.get("system", {}))
    result = FullResult(success=True, error="", runs=runs, system=system)

    return result, task


def serialize_result_to_dict(result: FullResult) -> dict:
    """Serialize FullResult to a JSON-serializable dictionary."""
    runs_dict = {}
    for run_name, eval_result in result.runs.items():
        run_data = {
            "start": eval_result.start.isoformat(),
            "end": eval_result.end.isoformat(),
            "compilation": dataclasses.asdict(eval_result.compilation) if eval_result.compilation else None,
            "run": dataclasses.asdict(eval_result.run) if eval_result.run else None,
            "profile": dataclasses.asdict(eval_result.profile) if eval_result.profile else None,
        }
        runs_dict[run_name] = run_data
    
    result_dict = {
        "success": result.success,
        "error": result.error,
        "runs": runs_dict,
        "system": dataclasses.asdict(result.system),
    }
    return result_dict


def print_benchmark_details(result: FullResult):
    """Print per-benchmark statistics for a leaderboard run if available."""
    if "leaderboard" not in result.runs:
        return

    run_res = result.runs["leaderboard"].run
    if not run_res or not run_res.result:
        return

    data = run_res.result
    if "benchmark-count" not in data:
        return

    num_benchmarks = int(data["benchmark-count"])
    print(f"\nLeaderboard benchmarks: {num_benchmarks}")
    for i in range(num_benchmarks):
        prefix = f"benchmark.{i}."
        mean_ns = float(data.get(prefix + "mean", 0.0))
        std_ns = float(data.get(prefix + "std", 0.0))
        best_ns = float(data.get(prefix + "best", 0.0))
        worst_ns = float(data.get(prefix + "worst", 0.0))

        mean_us = mean_ns / 1e3 if mean_ns else 0.0
        std_us = std_ns / 1e3 if std_ns else 0.0
        best_us = best_ns / 1e3 if best_ns else 0.0
        worst_us = worst_ns / 1e3 if worst_ns else 0.0

        print(f"  Benchmark {i}:")
        print(f"    mean:   {mean_us:.3f} us")
        print(f"    std:    {std_us:.3f} us")
        print(f"    best:   {best_us:.3f} us")
        print(f"    worst:  {worst_us:.3f} us")


def print_result(result: FullResult, task: LeaderboardTask | None = None):
    """Pretty print a FullResult and optionally the leaderboard score."""
    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(f"Success: {result.success}")

    if not result.success:
        print("\nSystem Info:")
        if result.system.gpu:
            print(f"  GPU: {result.system.gpu}")
        if result.system.cpu:
            print(f"  CPU: {result.system.cpu}")
        print(f"  Requeues: {result.system.requeues}")
        print(f"Error: {result.error}")
        return

    print("\nSystem Info:")
    print(f"  GPU: {result.system.gpu}")
    print(f"  CPU: {result.system.cpu}")
    print(f"  Requeues: {result.system.requeues}")
    if result.system.torch:
        print(f"  Torch: {result.system.torch}")
    if result.system.runtime:
        print(f"  Runtime: {result.system.runtime}")

    print(f"\nRuns: {len(result.runs)}")
    for run_name, run_result in result.runs.items():
        print(f"\n  Run: {run_name}")
        print(f"    Start: {run_result.start}")
        print(f"    End:   {run_result.end}")

        if run_result.compilation:
            comp = run_result.compilation
            print("    Compilation:")
            print(f"      Success:  {comp.success}")
            if not comp.success:
                print(f"      ExitCode: {comp.exit_code}")
                print(f"      Stderr:   {comp.stderr[:200]}...")

        if run_result.run:
            run = run_result.run
            print("    Execution:")
            print(f"      Success:   {run.success}")
            print(f"      Passed:    {run.passed}")
            print(f"      Duration:  {run.duration:.2f}s")
            print(f"      Exit Code: {run.exit_code}")

            if run.stdout:
                print(f"      Stdout:\n{run.stdout[:500]}{'...' if len(run.stdout) > 500 else ''}")
            if run.stderr:
                print(f"      Stderr:\n{run.stderr[:500]}{'...' if len(run.stderr) > 500 else ''}")

    # If we have a task and a leaderboard run, print per-benchmark stats and score
    if task is not None and "leaderboard" in result.runs:
        print_benchmark_details(result)
        try:
            score_seconds = compute_score(result, task, submission_id=-1)
            score_us = score_seconds * 1_000_000
            print(f"\nOverall leaderboard score (microseconds, {task.ranking_by.value}): {score_us:.3f} us")
        except Exception as e:
            print(f"\nCould not compute leaderboard score: {e}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run mla-decode submission on GitHub Actions using the official task definition.",
    )
    parser.add_argument(
        "--submission",
        "-s",
        required=True,
        help="Path to your mla-decode submission.py file.",
    )
    parser.add_argument(
        "--gpu",
        "-g",
        default="MI300",
        choices=[g.name for g in GitHubGPU],
        help="GitHub GPU type to use (default: MI300).",
    )
    parser.add_argument(
        "--mode",
        "-m",
        default="leaderboard",
        choices=[m.value for m in SubmissionMode],
        help="Submission mode (default: leaderboard).",
    )
    parser.add_argument(
        "--github-repo",
        help="GitHub repository (owner/repo). Overrides GITHUB_REPO env var.",
    )
    parser.add_argument(
        "--github-token",
        help="GitHub token. Overrides GITHUB_TOKEN env var.",
    )
    parser.add_argument(
        "--github-branch",
        default="main",
        help="GitHub branch to use (default: main). Overrides GITHUB_WORKFLOW_BRANCH env var.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Output directory for saving results. Results will be saved as <submission_name>.out in this directory.",
    )
    parser.add_argument(
        "--runner",
        "-r",
        help="GitHub Actions runner label to use (default: amd-arc-runner for ARC, or amd-docker for manual). Overrides GPU-based defaults.",
    )
    parser.add_argument(
        "--workflow-file",
        "-w",
        help="GitHub Actions workflow file to use (default: amd-mla-decode-workflow-ARC.yml). Can be just the filename or full path like .github/workflows/filename.yml.",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    submission_path = Path(args.submission)
    if not submission_path.exists():
        raise FileNotFoundError(f"Submission file not found: {submission_path}")

    submission_code = submission_path.read_text()

    result, task = await run_mla_decode_on_github(
        submission_code=submission_code,
        gpu_type=args.gpu,
        mode=args.mode,
        github_repo=args.github_repo,
        github_token=args.github_token,
        github_branch=args.github_branch,
        runner_name=args.runner,
        workflow_file=args.workflow_file,
    )

    # Save result to output file if output directory is specified
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Use the submission file name (without extension) as the output file name
        submission_stem = submission_path.stem
        output_file = output_dir / f"{submission_stem}.out"
        
        result_dict = serialize_result_to_dict(result)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, indent=2)
        
        print(f"\nResult saved to: {output_file}")
    else:
        print_result(result, task)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")

