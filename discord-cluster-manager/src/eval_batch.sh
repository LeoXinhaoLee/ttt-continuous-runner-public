#!/bin/bash

export MODAL_TOKEN_ID=
export MODAL_TOKEN_SECRET=

set -x

# modal deploy runners/modal_runner_archs.py

## Put kernel .py files under `submissions-dir`: 1.py, 2.py, 3.py, ...
## Adjust batch size for parallel evaluation
## Right now 3 rounds of tests are done in the bash script loop
for gpu in A100 H100 B200; do

  for i in {1..3}; do
        python run_trimul_modal_batch.py \
        --submissions-dir bioml/trimul/submission_samples/${gpu}_leaderboard \
        --gpu ${gpu} \
        --mode leaderboard \
        --batch-size 16 \
        --workers 16 \
        --output-dir results/${gpu}_leaderboard/test_${i}
    done
  
  python extract_eval.py results/${gpu}_leaderboard

done
