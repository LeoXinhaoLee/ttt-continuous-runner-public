#!/bin/bash

# export LD_LIBRARY_PATH=/workspace/pytorch_amd/build/lib:$LD_LIBRARY_PATH

# export CUSTOM_KERNEL_MODULE="kernels/1.py"
# python eval_local.py results/MI300x_debug/1/test1.out

# export CUSTOM_KERNEL_MODULE="kernels/4.py"
# python eval_local.py results/MI300x_debug/4/test1.out

# export CUSTOM_KERNEL_MODULE="kernels/5.py"
# python eval_local.py results/MI300x_debug/5/test1.out

# export CUSTOM_KERNEL_MODULE="kernels/20.py"
# python eval_local.py results/MI300x_debug/20/test1.out

# for i in {1..5}; do

#     for j in {1..3}; do

#     export CUSTOM_KERNEL_MODULE="kernels/${i}.py"
#     python eval_local.py results/MI300x/${i}/test${j}.out

#     done

# done

# for i in {1..34}; do

#     for j in {1..3}; do

#     ## PT 2.7.1
#     # mkdir -p results/MI300x_torch_2.7.1/out/${i}
#     # mkdir -p results/MI300x_torch_2.7.1/log/${i}
#     # export CUSTOM_KERNEL_MODULE="kernels/${i}.py"
#     # python eval_local.py results/MI300x_torch_2.7.1/out/${i}/test${j}.out > results/MI300x_torch_2.7.1/log/${i}/test${j}.log 2>&1

#     ## PT 2.8.0
#     mkdir -p results/MI300x_torch_2.8.0/out/${i}
#     mkdir -p results/MI300x_torch_2.8.0/log/${i}
#     export CUSTOM_KERNEL_MODULE="kernels/${i}.py"
#     python eval_local.py results/MI300x_torch_2.8.0/out/${i}/test${j}.out > results/MI300x_torch_2.8.0/log/${i}/test${j}.log 2>&1

#     done

# done

# for i in 3 18 19 20 23 28 32; do

#     for j in 1; do

#     ## PT 2.8.0
#     mkdir -p results/MI300x_torch_2.8.0/out/${i}
#     mkdir -p results/MI300x_torch_2.8.0/log/${i}
#     export CUSTOM_KERNEL_MODULE="kernels/${i}.py"
#     python eval_local.py results/MI300x_torch_2.8.0/out/${i}/test${j}.out > results/MI300x_torch_2.8.0/log/${i}/test${j}.log 2>&1

#     done

# done

######

for i in {0..15}; do

    mkdir -p results/model_gen/out
    mkdir -p results/model_gen/log
    export CUSTOM_KERNEL_MODULE="samples_xh/sample_${i}.py"
    python eval_local.py results/model_gen/out/${i}.out > results/model_gen/log/${i}.log 2>&1

done

