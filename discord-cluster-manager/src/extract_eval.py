#!/usr/bin/env python3
"""
Extract GPU type and geometric mean from .out files in a leaderboard results folder.
Outputs TSV with format: Leaderboard_name GPU Sample_ID test1 test2 test3
"""
import re
import sys
from pathlib import Path
import csv
from collections import defaultdict

# Regex patterns to extract GPU type and geometric mean
GPU_RE = re.compile(r"GPU:\s*(.+?)$", re.MULTILINE)
GEOM_MEAN_RE = re.compile(
    r"Overall leaderboard score\s*\(microseconds,\s*geom\)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*us"
)


def extract_gpu_and_geometric_mean(text: str):
    """Extract GPU type and geometric mean from .out file content."""
    gpu_match = GPU_RE.search(text)
    geom_match = GEOM_MEAN_RE.search(text)
    
    gpu = gpu_match.group(1).strip() if gpu_match else None
    geom_mean = float(geom_match.group(1)) if geom_match else None
    
    return gpu, geom_mean


def process_leaderboard_folder(leaderboard_path: Path):
    """
    Process a leaderboard folder (e.g., H100_leaderboard).
    Returns a dict mapping (filename_base, gpu) -> {test_1: geom_mean, test_2: geom_mean, test_3: geom_mean}
    """
    results = defaultdict(lambda: {"test_1": None, "test_2": None, "test_3": None, "gpu": None})
    
    leaderboard_name = leaderboard_path.name
    
    # Process test_1, test_2, test_3 folders
    for test_num in [1, 2, 3]:
        test_folder = leaderboard_path / f"test_{test_num}"
        if not test_folder.exists() or not test_folder.is_dir():
            continue
        
        # Process all .out files in this test folder
        for out_file in sorted(test_folder.glob("*.out")):
            try:
                text = out_file.read_text(errors="replace")
                gpu, geom_mean = extract_gpu_and_geometric_mean(text)
                
                if gpu is None or geom_mean is None:
                    print(f"Warning: Could not extract GPU or geometric mean from {out_file}", file=sys.stderr)
                    continue
                
                # Use filename without extension as key
                filename_base = out_file.stem
                key = filename_base
                
                # Store results
                test_key = f"test_{test_num}"
                if results[key]["gpu"] is None:
                    results[key]["gpu"] = gpu
                elif results[key]["gpu"] != gpu:
                    print(f"Warning: GPU mismatch for {filename_base}: {results[key]['gpu']} vs {gpu}", file=sys.stderr)
                
                results[key][test_key] = geom_mean
                
            except Exception as e:
                print(f"Error processing {out_file}: {e}", file=sys.stderr)
                continue
    
    return leaderboard_name, results


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <leaderboard_folder>", file=sys.stderr)
        print(f"Example: {sys.argv[0]} results/H100_leaderboard", file=sys.stderr)
        sys.exit(1)
    
    leaderboard_path = Path(sys.argv[1])
    
    if not leaderboard_path.exists():
        print(f"Error: Path {leaderboard_path} does not exist", file=sys.stderr)
        sys.exit(1)
    
    if not leaderboard_path.is_dir():
        print(f"Error: {leaderboard_path} is not a directory", file=sys.stderr)
        sys.exit(1)
    
    # Process the leaderboard folder
    leaderboard_name, results = process_leaderboard_folder(leaderboard_path)
    
    # Output TSV
    output_file = leaderboard_path / f"{leaderboard_name}_results.tsv"
    
    with output_file.open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        # Write header
        writer.writerow(["Leaderboard_name", "GPU", "Sample_ID", "test1", "test2", "test3"])
        
        # Write data rows (sorted by filename)
        for filename_base in sorted(results.keys()):
            row = results[filename_base]
            gpu = row["gpu"] if row["gpu"] else "N/A"
            test1 = row["test_1"] if row["test_1"] is not None else ""
            test2 = row["test_2"] if row["test_2"] is not None else ""
            test3 = row["test_3"] if row["test_3"] is not None else ""
            
            writer.writerow([leaderboard_name, gpu, filename_base, test1, test2, test3])
    
    print(f"Wrote {len(results)} rows to {output_file}")


if __name__ == "__main__":
    main()

