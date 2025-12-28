#!/usr/bin/env python3
"""
Extract geometric mean from all .out files under results/
"""
import re
from pathlib import Path

def extract_geometric_mean(file_path):
    """Extract geometric mean value from a .out file."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            # Match both "geometric-mean: <value>" and "geometric-mean (us): <value>"
            match = re.search(r'geometric-mean(?:\s*\(us\))?:\s*([\d.]+)', content)
            if match:
                return float(match.group(1))
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return None

def main():
    # results_dir = Path(__file__).parent / "results" / "MI300x_torch_2.7.1" / "out"
    results_dir = Path(__file__).parent / "results" / "MI300x_torch_2.8.0" / "out"
    output_file = Path(__file__).parent / "geometric_means.tsv"
    
    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        return
    
    # Find all .out files
    out_files = list(results_dir.rglob("*.out"))
    
    if not out_files:
        print("No .out files found in results/")
        return
    
    print(f"Found {len(out_files)} .out file(s)")
    
    # Sort files numerically by extracting numbers from path
    def natural_sort_key(path):
        """Create a sort key for natural/numeric sorting."""
        relative_path = path.relative_to(results_dir)
        parts = relative_path.parts
        # Extract numeric parts and convert to int for proper numeric sorting
        # Structure: {number}/test{number}.out
        key_parts = []
        for part in parts:
            # Extract all numbers from the part
            numbers = re.findall(r'\d+', part)
            if numbers:
                # Convert all numbers to int for proper numeric sorting
                key_parts.extend([int(n) for n in numbers])
            else:
                # For non-numeric parts, use string comparison
                key_parts.append(part)
        return key_parts
    
    # Extract geometric means and write to TSV
    with open(output_file, 'w') as f:
        # Write header
        f.write("file\tgeometric_mean_us\n")
        
        # Write data rows, sorted numerically
        for out_file in sorted(out_files, key=natural_sort_key):
            geometric_mean = extract_geometric_mean(out_file)
            relative_path = out_file.relative_to(results_dir)
            
            if geometric_mean is not None:
                f.write(f"{relative_path}\t{geometric_mean:.6f}\n")
            else:
                f.write(f"{relative_path}\tN/A\n")
    
    print(f"Results written to {output_file}")

if __name__ == "__main__":
    main()

