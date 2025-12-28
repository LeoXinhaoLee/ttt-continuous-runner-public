from pip._internal import main as pip_main
pip_main(["install","tilelang-rocm"])

import math
from dataclasses import dataclass
import torch
from torch import nn
import torch.nn.functional as F
from task import input_t, output_t
import tilelang
from tilelang.autotuner import *
import tilelang.language as T
from torch.profiler import profile, record_function, ProfilerActivity
import time

tilelang.cache.clear_cache()
# tilelang.disable_cache()

BASE_CONFIGS = {
    128: {'block_N': 16, 'block_H': 64, 'num_split': 1, 'num_stages': 1, 'enable_rasterization': False},
    512: {'block_N': 16, 'block_H': 64, 'num_split': 1, 'num_stages': 0, 'enable_rasterization': False},
    1024: {'block_N': 16, 'block_H': 64, 'num_split': 1, 'num_stages': 0, 'enable_rasterization': False},
    2048: {'block_N': 16, 'block_H': 64, 'num_split': 1, 'num_stages': 0, 'enable_rasterization': False},
    4096: {'block_N': 16, 'block_H': 64, 'num_split': 1, 'num_stages': 0, 'enable_rasterization': False},
    6144: {'block_N': 16, 'block_H': 64, 'num_split': 2, 'num_stages': 0, 'enable_rasterization': False}
}

PREFILL_CONFIGS = BASE_CONFIGS.copy()
config_4096 = BASE_CONFIGS[4096]
for i in range(4097, 4197):  # 4097到4196
    PREFILL_CONFIGS[i] = config_4096


def get_optimal_kernel(batch, heads, kv_head_num, seqlen_kv, dim, pe_dim):
    use_autotune = seqlen_kv > 6144
    if use_autotune:
        print(f"[AUTO TUNE] Using autotune for seqlen_kv={seqlen_kv}")
        
        # 使用 autotune 版本的 kernel
        kernel = flashmla_decode_autotune(
            batch,
            heads,
            kv_head_num,
            seqlen_kv+1,
            dim,
            pe_dim
        )
        best_config = kernel.config
        print(f"[AUTO TUNE] Best config: {best_config}")
        return kernel, best_config
    else:
        print(f"[NO AUTO TUNE] Using no autotune for seqlen_kv={seqlen_kv}")
        if seqlen_kv in PREFILL_CONFIGS:
            best_config = PREFILL_CONFIGS[seqlen_kv]
            kernel = flashmla_decode_no_tuning(
                batch,
                heads,
                kv_head_num,
                seqlen_kv+1,
                dim,
                pe_dim,
                **best_config
            )
            return kernel, best_config
        else:
            return None


@tilelang.jit(out_idx=[6])
def flashmla_decode_no_tuning(batch,
                    heads,
                    kv_head_num,
                    seqlen_kv,
                    dim,
                    pe_dim,
                    block_N,
                    block_H,
                    num_split,
                    threads=256,
                    num_stages=2,
                    enable_rasterization=True):
    # scale = (1.0 / (dim + pe_dim))**0.5 * 1.44269504  # log2(e)
    scale = (1.0 / (128 + 64))**0.5 * 1.44269504
    # dtype = "float16"
    dtype = "bfloat16"
    accum_dtype = "float"
    kv_group_num = heads // kv_head_num
    VALID_BLOCK_H = min(block_H, kv_group_num)
    assert kv_head_num == 1, "kv_head_num must be 1"
    k_pack = 1
    vec_size = 4 * k_pack

    @T.macro
    def flash_attn(
            Q: T.Tensor([batch, heads, dim], dtype),
            Q_pe: T.Tensor([batch, heads, pe_dim], dtype),
            KV: T.Tensor([batch, seqlen_kv, kv_head_num, dim], dtype),
            K_pe: T.Tensor([batch, seqlen_kv, kv_head_num, pe_dim], dtype),
            Output: T.Tensor([batch, heads, dim], dtype),
    ):
        with T.Kernel(batch, heads // min(block_H, kv_group_num), threads=threads) as (bx, by):
            Q_local = T.alloc_fragment([block_H, dim], dtype)
            Q_pe_local = T.alloc_fragment([block_H, pe_dim], dtype)
            KV_shared = T.alloc_shared([block_N, dim], dtype)
            K_pe_shared = T.alloc_shared([block_N, pe_dim], dtype)
            acc_s = T.alloc_fragment([block_H, block_N], accum_dtype)
            acc_s_cast = T.alloc_fragment([block_H, block_N], dtype)
            acc_o = T.alloc_fragment([block_H, dim], accum_dtype)
            scores_max = T.alloc_fragment([block_H], accum_dtype)
            scores_max_prev = T.alloc_fragment([block_H], accum_dtype)
            scores_scale = T.alloc_fragment([block_H], accum_dtype)
            scores_sum = T.alloc_fragment([block_H], accum_dtype)
            logsum = T.alloc_fragment([block_H], accum_dtype)

            cur_kv_head = by // (kv_group_num // block_H)
            T.use_swizzle(10, enable=enable_rasterization)

            T.copy(Q[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :], Q_local)
            T.copy(Q_pe[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :], Q_pe_local)
            T.fill(acc_o, 0)
            T.fill(logsum, 0)
            T.fill(scores_max, -T.infinity(accum_dtype))

            loop_range = T.ceildiv(seqlen_kv, block_N)
            for k in T.Pipelined(loop_range, num_stages=num_stages):
                T.copy(KV[bx, k * block_N:(k + 1) * block_N, cur_kv_head, :], KV_shared, coalesced_width=vec_size)
                T.copy(K_pe[bx, k * block_N:(k + 1) * block_N, cur_kv_head, :], K_pe_shared, coalesced_width=vec_size)
                T.clear(acc_s)
                T.gemm(Q_local, KV_shared, acc_s, transpose_B=True, policy=T.GemmWarpPolicy.FullRow)
                T.gemm(
                    Q_pe_local,
                    K_pe_shared,
                    acc_s,
                    transpose_B=True,
                    policy=T.GemmWarpPolicy.FullRow)
                T.copy(scores_max, scores_max_prev)
                T.fill(scores_max, -T.infinity(accum_dtype))
                T.reduce_max(acc_s, scores_max, dim=1, clear=False)
                for i in T.Parallel(block_H):
                    scores_scale[i] = T.exp2(scores_max_prev[i] * scale - scores_max[i] * scale)
                for i, j in T.Parallel(block_H, block_N):
                    acc_s[i, j] = T.exp2(acc_s[i, j] * scale - scores_max[i] * scale)
                T.reduce_sum(acc_s, scores_sum, dim=1)
                # T.copy(acc_s, S_shared)
                T.copy(acc_s, acc_s_cast)
                for i in T.Parallel(block_H):
                    logsum[i] = logsum[i] * scores_scale[i] + scores_sum[i]
                for i, j in T.Parallel(block_H, dim):
                    acc_o[i, j] *= scores_scale[i]
                T.gemm(acc_s_cast, KV_shared, acc_o, policy=T.GemmWarpPolicy.FullRow)
            for i, j in T.Parallel(block_H, dim):
                acc_o[i, j] /= logsum[i]
            T.copy(acc_o, Output[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :])

    @T.macro
    def flash_attn_split(
            Q: T.Tensor([batch, heads, dim], dtype),
            Q_pe: T.Tensor([batch, heads, pe_dim], dtype),
            KV: T.Tensor([batch, seqlen_kv, kv_head_num, dim], dtype),
            K_pe: T.Tensor([batch, seqlen_kv, kv_head_num, pe_dim], dtype),
            glse: T.Tensor([batch, heads, num_split], accum_dtype),
            Output_partial: T.Tensor([batch, heads, num_split, dim], accum_dtype),
    ):
        with T.Kernel(
                batch, heads // min(block_H, kv_group_num), num_split,
                threads=threads) as (bx, by, bz):
            Q_local = T.alloc_fragment([block_H, dim], dtype)
            Q_pe_local = T.alloc_fragment([block_H, pe_dim], dtype)
            KV_shared = T.alloc_shared([block_N, dim], dtype)
            K_pe_shared = T.alloc_shared([block_N, pe_dim], dtype)
            acc_s = T.alloc_fragment([block_H, block_N], accum_dtype)
            acc_s_cast = T.alloc_fragment([block_H, block_N], dtype)
            acc_o = T.alloc_fragment([block_H, dim], accum_dtype)
            scores_max = T.alloc_fragment([block_H], accum_dtype)
            scores_max_prev = T.alloc_fragment([block_H], accum_dtype)
            scores_scale = T.alloc_fragment([block_H], accum_dtype)
            scores_sum = T.alloc_fragment([block_H], accum_dtype)
            logsum = T.alloc_fragment([block_H], accum_dtype)

            cur_kv_head = by // (kv_group_num // block_H)
            T.use_swizzle(10, enable=enable_rasterization)
            T.copy(Q[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :], Q_local)
            T.copy(Q_pe[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :], Q_pe_local)
            T.fill(acc_o, 0)
            T.fill(logsum, 0)
            T.fill(scores_max, -T.infinity(accum_dtype))

            loop_range = T.ceildiv((seqlen_kv // num_split), block_N)
            for k in T.Pipelined(loop_range, num_stages=num_stages):
                kv_start = (seqlen_kv // num_split) * bz + k * block_N
                kv_end = (seqlen_kv // num_split) * bz + (k + 1) * block_N
                T.copy(KV[bx, kv_start:kv_end, cur_kv_head, :], KV_shared, coalesced_width=vec_size)
                T.copy(K_pe[bx, kv_start:kv_end, cur_kv_head, :], K_pe_shared, coalesced_width=vec_size)
                T.clear(acc_s)
                T.gemm(Q_local, KV_shared, acc_s, transpose_B=True, policy=T.GemmWarpPolicy.FullRow)
                T.gemm(
                    Q_pe_local,
                    K_pe_shared,
                    acc_s,
                    transpose_B=True,
                    policy=T.GemmWarpPolicy.FullRow)
                T.copy(scores_max, scores_max_prev)
                T.fill(scores_max, -T.infinity(accum_dtype))
                T.reduce_max(acc_s, scores_max, dim=1, clear=False)
                for i in T.Parallel(block_H):
                    scores_scale[i] = T.exp2(scores_max_prev[i] * scale - scores_max[i] * scale)
                for i, j in T.Parallel(block_H, block_N):
                    acc_s[i, j] = T.exp2(acc_s[i, j] * scale - scores_max[i] * scale)
                T.reduce_sum(acc_s, scores_sum, dim=1)
                T.copy(acc_s, acc_s_cast)
                for i in T.Parallel(block_H):
                    logsum[i] = logsum[i] * scores_scale[i] + scores_sum[i]
                for i, j in T.Parallel(block_H, dim):
                    acc_o[i, j] *= scores_scale[i]
                T.gemm(acc_s_cast, KV_shared, acc_o, policy=T.GemmWarpPolicy.FullRow)
            for i, j in T.Parallel(block_H, dim):
                acc_o[i, j] /= logsum[i]
            for i in T.Parallel(block_H):
                logsum[i] = T.log2(logsum[i]) + scores_max[i] * scale
            T.copy(logsum, glse[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, bz])
            T.copy(acc_o, Output_partial[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, bz, :])

    @T.macro
    def combine(
            glse: T.Tensor([batch, heads, num_split], accum_dtype),
            Output_partial: T.Tensor([batch, heads, num_split, dim], accum_dtype),
            Output: T.Tensor([batch, heads, dim], dtype),
    ):
        with T.Kernel(heads, batch, threads=128) as (by, bz):
            po_local = T.alloc_fragment([dim], accum_dtype)
            o_accum_local = T.alloc_fragment([dim], accum_dtype)
            lse_local_split = T.alloc_local([1], accum_dtype)
            lse_logsum_local = T.alloc_local([1], accum_dtype)
            lse_max_local = T.alloc_local([1], accum_dtype)
            scale_local = T.alloc_local([1], accum_dtype)

            T.annotate_layout({
                lse_logsum_local: T.Fragment(lse_logsum_local.shape, forward_thread_fn=lambda i: i),
            })

            T.clear(lse_logsum_local)
            T.clear(o_accum_local)
            lse_max_local[0] = -T.infinity(accum_dtype)
            for k in T.serial(num_split):
                lse_max_local[0] = T.max(lse_max_local[0], glse[bz, by, k])
            for k in T.Pipelined(num_split, num_stages=1):
                lse_local_split[0] = glse[bz, by, k]
                lse_logsum_local[0] += T.exp2(lse_local_split[0] - lse_max_local[0])
            lse_logsum_local[0] = T.log2(lse_logsum_local[0]) + lse_max_local[0]
            for k in T.serial(num_split):
                for i in T.Parallel(dim):
                    po_local[i] = Output_partial[bz, by, k, i]
                lse_local_split[0] = glse[bz, by, k]
                scale_local[0] = T.exp2(lse_local_split[0] - lse_logsum_local[0])
                for i in T.Parallel(dim):
                    o_accum_local[i] += po_local[i] * scale_local[0]
            for i in T.Parallel(dim):
                Output[bz, by, i] = o_accum_local[i]

    @T.prim_func
    def main_split(
            Q: T.Tensor([batch, heads, dim], dtype),
            Q_pe: T.Tensor([batch, heads, pe_dim], dtype),
            KV: T.Tensor([batch, seqlen_kv, kv_head_num, dim], dtype),
            K_pe: T.Tensor([batch, seqlen_kv, kv_head_num, pe_dim], dtype),
            glse: T.Tensor([batch, heads, num_split], accum_dtype),
            Output_partial: T.Tensor([batch, heads, num_split, dim], accum_dtype),
            Output: T.Tensor([batch, heads, dim], dtype),
    ):
        flash_attn_split(Q, Q_pe, KV, K_pe, glse, Output_partial)
        combine(glse, Output_partial, Output)

    @T.prim_func
    def main_no_split(
            Q: T.Tensor([batch, heads, dim], dtype),
            Q_pe: T.Tensor([batch, heads, pe_dim], dtype),
            KV: T.Tensor([batch, seqlen_kv, kv_head_num, dim], dtype),
            K_pe: T.Tensor([batch, seqlen_kv, kv_head_num, pe_dim], dtype),
            glse: T.Tensor([batch, heads, num_split], accum_dtype),
            Output_partial: T.Tensor([batch, heads, num_split, dim], accum_dtype),
            Output: T.Tensor([batch, heads, dim], dtype),
    ):
        flash_attn(Q, Q_pe, KV, K_pe, Output)

    if num_split > 1:
        return main_split
    else:
        return main_no_split


def get_configs():
    import itertools
    block_N = [16, 32, 64, 128]
    block_H = [16, 32, 64, 128]
    num_split = [1, 2, 4, 8, 16]
    num_stages = [0, 1]
    enable_rasterization = [False, True]
    
    # block_N = [32]
    # block_H = [64]
    # num_split = [4]
    # num_stages = [0]
    # enable_rasterization = [False]

    _configs = list(itertools.product(block_N, block_H, num_split, num_stages, enable_rasterization))
    
    return [{
        "block_N": c[0],
        "block_H": c[1],
        "num_split": c[2],
        "num_stages": c[3],
        "enable_rasterization": c[4],
    } for c in _configs]

@tilelang.autotune(configs=get_configs(), cache_input_tensors=False)
@tilelang.jit(out_idx=[6])
def flashmla_decode_autotune(batch,
                    heads,
                    kv_head_num,
                    seqlen_kv,
                    dim,
                    pe_dim,
                    block_N,
                    block_H,
                    num_split,
                    threads=256,
                    num_stages=2,
                    enable_rasterization=True):
    # scale = (1.0 / (dim + pe_dim))**0.5 * 1.44269504  # log2(e)
    scale = (1.0 / (128 + 64))**0.5 * 1.44269504
    # dtype = "float16"
    dtype = "bfloat16"
    accum_dtype = "float"
    kv_group_num = heads // kv_head_num
    VALID_BLOCK_H = min(block_H, kv_group_num)
    assert kv_head_num == 1, "kv_head_num must be 1"
    k_pack = 1
    vec_size = 4 * k_pack

    @T.macro
    def flash_attn(
            Q: T.Tensor([batch, heads, dim], dtype),
            Q_pe: T.Tensor([batch, heads, pe_dim], dtype),
            KV: T.Tensor([batch, seqlen_kv, kv_head_num, dim], dtype),
            K_pe: T.Tensor([batch, seqlen_kv, kv_head_num, pe_dim], dtype),
            Output: T.Tensor([batch, heads, dim], dtype),
    ):
        with T.Kernel(batch, heads // min(block_H, kv_group_num), threads=threads) as (bx, by):
            Q_local = T.alloc_fragment([block_H, dim], dtype)
            Q_pe_local = T.alloc_fragment([block_H, pe_dim], dtype)
            KV_shared = T.alloc_shared([block_N, dim], dtype)
            K_pe_shared = T.alloc_shared([block_N, pe_dim], dtype)
            acc_s = T.alloc_fragment([block_H, block_N], accum_dtype)
            acc_s_cast = T.alloc_fragment([block_H, block_N], dtype)
            acc_o = T.alloc_fragment([block_H, dim], accum_dtype)
            scores_max = T.alloc_fragment([block_H], accum_dtype)
            scores_max_prev = T.alloc_fragment([block_H], accum_dtype)
            scores_scale = T.alloc_fragment([block_H], accum_dtype)
            scores_sum = T.alloc_fragment([block_H], accum_dtype)
            logsum = T.alloc_fragment([block_H], accum_dtype)

            cur_kv_head = by // (kv_group_num // block_H)
            T.use_swizzle(10, enable=enable_rasterization)

            T.copy(Q[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :], Q_local)
            T.copy(Q_pe[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :], Q_pe_local)
            T.fill(acc_o, 0)
            T.fill(logsum, 0)
            T.fill(scores_max, -T.infinity(accum_dtype))

            loop_range = T.ceildiv(seqlen_kv, block_N)
            for k in T.Pipelined(loop_range, num_stages=num_stages):
                T.copy(KV[bx, k * block_N:(k + 1) * block_N, cur_kv_head, :], KV_shared, coalesced_width=vec_size)
                T.copy(K_pe[bx, k * block_N:(k + 1) * block_N, cur_kv_head, :], K_pe_shared, coalesced_width=vec_size)
                T.clear(acc_s)
                T.gemm(Q_local, KV_shared, acc_s, transpose_B=True, policy=T.GemmWarpPolicy.FullRow)
                T.gemm(
                    Q_pe_local,
                    K_pe_shared,
                    acc_s,
                    transpose_B=True,
                    policy=T.GemmWarpPolicy.FullRow)
                T.copy(scores_max, scores_max_prev)
                T.fill(scores_max, -T.infinity(accum_dtype))
                T.reduce_max(acc_s, scores_max, dim=1, clear=False)
                for i in T.Parallel(block_H):
                    scores_scale[i] = T.exp2(scores_max_prev[i] * scale - scores_max[i] * scale)
                for i, j in T.Parallel(block_H, block_N):
                    acc_s[i, j] = T.exp2(acc_s[i, j] * scale - scores_max[i] * scale)
                T.reduce_sum(acc_s, scores_sum, dim=1)
                # T.copy(acc_s, S_shared)
                T.copy(acc_s, acc_s_cast)
                for i in T.Parallel(block_H):
                    logsum[i] = logsum[i] * scores_scale[i] + scores_sum[i]
                for i, j in T.Parallel(block_H, dim):
                    acc_o[i, j] *= scores_scale[i]
                T.gemm(acc_s_cast, KV_shared, acc_o, policy=T.GemmWarpPolicy.FullRow)
            for i, j in T.Parallel(block_H, dim):
                acc_o[i, j] /= logsum[i]
            T.copy(acc_o, Output[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :])

    @T.macro
    def flash_attn_split(
            Q: T.Tensor([batch, heads, dim], dtype),
            Q_pe: T.Tensor([batch, heads, pe_dim], dtype),
            KV: T.Tensor([batch, seqlen_kv, kv_head_num, dim], dtype),
            K_pe: T.Tensor([batch, seqlen_kv, kv_head_num, pe_dim], dtype),
            glse: T.Tensor([batch, heads, num_split], accum_dtype),
            Output_partial: T.Tensor([batch, heads, num_split, dim], accum_dtype),
    ):
        with T.Kernel(
                batch, heads // min(block_H, kv_group_num), num_split,
                threads=threads) as (bx, by, bz):
            Q_local = T.alloc_fragment([block_H, dim], dtype)
            Q_pe_local = T.alloc_fragment([block_H, pe_dim], dtype)
            KV_shared = T.alloc_shared([block_N, dim], dtype)
            K_pe_shared = T.alloc_shared([block_N, pe_dim], dtype)
            acc_s = T.alloc_fragment([block_H, block_N], accum_dtype)
            acc_s_cast = T.alloc_fragment([block_H, block_N], dtype)
            acc_o = T.alloc_fragment([block_H, dim], accum_dtype)
            scores_max = T.alloc_fragment([block_H], accum_dtype)
            scores_max_prev = T.alloc_fragment([block_H], accum_dtype)
            scores_scale = T.alloc_fragment([block_H], accum_dtype)
            scores_sum = T.alloc_fragment([block_H], accum_dtype)
            logsum = T.alloc_fragment([block_H], accum_dtype)

            cur_kv_head = by // (kv_group_num // block_H)
            T.use_swizzle(10, enable=enable_rasterization)
            T.copy(Q[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :], Q_local)
            T.copy(Q_pe[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, :], Q_pe_local)
            T.fill(acc_o, 0)
            T.fill(logsum, 0)
            T.fill(scores_max, -T.infinity(accum_dtype))

            loop_range = T.ceildiv((seqlen_kv // num_split), block_N)
            for k in T.Pipelined(loop_range, num_stages=num_stages):
                kv_start = (seqlen_kv // num_split) * bz + k * block_N
                kv_end = (seqlen_kv // num_split) * bz + (k + 1) * block_N
                T.copy(KV[bx, kv_start:kv_end, cur_kv_head, :], KV_shared, coalesced_width=vec_size)
                T.copy(K_pe[bx, kv_start:kv_end, cur_kv_head, :], K_pe_shared, coalesced_width=vec_size)
                T.clear(acc_s)
                T.gemm(Q_local, KV_shared, acc_s, transpose_B=True, policy=T.GemmWarpPolicy.FullRow)
                T.gemm(
                    Q_pe_local,
                    K_pe_shared,
                    acc_s,
                    transpose_B=True,
                    policy=T.GemmWarpPolicy.FullRow)
                T.copy(scores_max, scores_max_prev)
                T.fill(scores_max, -T.infinity(accum_dtype))
                T.reduce_max(acc_s, scores_max, dim=1, clear=False)
                for i in T.Parallel(block_H):
                    scores_scale[i] = T.exp2(scores_max_prev[i] * scale - scores_max[i] * scale)
                for i, j in T.Parallel(block_H, block_N):
                    acc_s[i, j] = T.exp2(acc_s[i, j] * scale - scores_max[i] * scale)
                T.reduce_sum(acc_s, scores_sum, dim=1)
                T.copy(acc_s, acc_s_cast)
                for i in T.Parallel(block_H):
                    logsum[i] = logsum[i] * scores_scale[i] + scores_sum[i]
                for i, j in T.Parallel(block_H, dim):
                    acc_o[i, j] *= scores_scale[i]
                T.gemm(acc_s_cast, KV_shared, acc_o, policy=T.GemmWarpPolicy.FullRow)
            for i, j in T.Parallel(block_H, dim):
                acc_o[i, j] /= logsum[i]
            for i in T.Parallel(block_H):
                logsum[i] = T.log2(logsum[i]) + scores_max[i] * scale
            T.copy(logsum, glse[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, bz])
            T.copy(acc_o, Output_partial[bx, by * VALID_BLOCK_H:(by + 1) * VALID_BLOCK_H, bz, :])

    @T.macro
    def combine(
            glse: T.Tensor([batch, heads, num_split], accum_dtype),
            Output_partial: T.Tensor([batch, heads, num_split, dim], accum_dtype),
            Output: T.Tensor([batch, heads, dim], dtype),
    ):
        with T.Kernel(heads, batch, threads=128) as (by, bz):
            po_local = T.alloc_fragment([dim], accum_dtype)
            o_accum_local = T.alloc_fragment([dim], accum_dtype)
            lse_local_split = T.alloc_local([1], accum_dtype)
            lse_logsum_local = T.alloc_local([1], accum_dtype)
            lse_max_local = T.alloc_local([1], accum_dtype)
            scale_local = T.alloc_local([1], accum_dtype)

            T.annotate_layout({
                lse_logsum_local: T.Fragment(lse_logsum_local.shape, forward_thread_fn=lambda i: i),
            })

            T.clear(lse_logsum_local)
            T.clear(o_accum_local)
            lse_max_local[0] = -T.infinity(accum_dtype)
            for k in T.serial(num_split):
                lse_max_local[0] = T.max(lse_max_local[0], glse[bz, by, k])
            for k in T.Pipelined(num_split, num_stages=1):
                lse_local_split[0] = glse[bz, by, k]
                lse_logsum_local[0] += T.exp2(lse_local_split[0] - lse_max_local[0])
            lse_logsum_local[0] = T.log2(lse_logsum_local[0]) + lse_max_local[0]
            for k in T.serial(num_split):
                for i in T.Parallel(dim):
                    po_local[i] = Output_partial[bz, by, k, i]
                lse_local_split[0] = glse[bz, by, k]
                scale_local[0] = T.exp2(lse_local_split[0] - lse_logsum_local[0])
                for i in T.Parallel(dim):
                    o_accum_local[i] += po_local[i] * scale_local[0]
            for i in T.Parallel(dim):
                Output[bz, by, i] = o_accum_local[i]

    @T.prim_func
    def main_split(
            Q: T.Tensor([batch, heads, dim], dtype),
            Q_pe: T.Tensor([batch, heads, pe_dim], dtype),
            KV: T.Tensor([batch, seqlen_kv, kv_head_num, dim], dtype),
            K_pe: T.Tensor([batch, seqlen_kv, kv_head_num, pe_dim], dtype),
            glse: T.Tensor([batch, heads, num_split], accum_dtype),
            Output_partial: T.Tensor([batch, heads, num_split, dim], accum_dtype),
            Output: T.Tensor([batch, heads, dim], dtype),
    ):
        flash_attn_split(Q, Q_pe, KV, K_pe, glse, Output_partial)
        combine(glse, Output_partial, Output)

    @T.prim_func
    def main_no_split(
            Q: T.Tensor([batch, heads, dim], dtype),
            Q_pe: T.Tensor([batch, heads, pe_dim], dtype),
            KV: T.Tensor([batch, seqlen_kv, kv_head_num, dim], dtype),
            K_pe: T.Tensor([batch, seqlen_kv, kv_head_num, pe_dim], dtype),
            glse: T.Tensor([batch, heads, num_split], accum_dtype),
            Output_partial: T.Tensor([batch, heads, num_split, dim], accum_dtype),
            Output: T.Tensor([batch, heads, dim], dtype),
    ):
        flash_attn(Q, Q_pe, KV, K_pe, Output)

    if num_split > 1:
        return main_split
    else:
        return main_no_split

class RoPE(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.d_model = d_model
        theta = 10000 ** (-torch.arange(0, d_model//2,dtype=torch.bfloat16) / (d_model//2))
        theta = theta.to("cuda")
        self.register_buffer("theta", theta)

    def rotate_half(self, x: torch.Tensor) -> torch.Tensor:
        x1, x2 = x.chunk(2, dim=-1)
        return torch.cat((-x2, x1), dim=-1)

    def forward(self, x: torch.Tensor, start_pos: int = 0) -> torch.Tensor:
        seq_len = x.size(-2)
        d_model = x.size(-1)
        assert d_model == self.d_model
        seq_idx = torch.arange(start_pos, start_pos + seq_len, device=x.device)
        idx_theta = torch.einsum('s,d->sd', seq_idx, self.theta)
        idx_theta2 = torch.cat([idx_theta, idx_theta], dim=-1)
        cos = idx_theta2.cos().to(torch.bfloat16)
        sin = idx_theta2.sin().to(torch.bfloat16)
        return x * cos + self.rotate_half(x) * sin


class KVCache(nn.Module):
    def __init__(self, kv_cache_shape: tuple) -> None:
        super().__init__()
        self.register_buffer('data', torch.zeros(kv_cache_shape, dtype=torch.bfloat16, device='cuda'))
        self.seq_len = 0
        self.zero()

    def zero(self) -> None:
        self.data.zero_()
    
    def get_data(self) -> torch.Tensor:
        return self.data

    def forward(self, c_kv: torch.Tensor) -> torch.Tensor:
        assert self.seq_len + c_kv.size(1) <= self.data.size(1), "KV Cache Exceeded"

        self.data = self.data.to(c_kv.dtype)
        self.data[
            :, self.seq_len : self.seq_len + c_kv.size(1), :
        ] = c_kv
        self.seq_len += c_kv.size(1)

        return self.data[:, :self.seq_len], self.seq_len

@dataclass
class Config:
    batch_size: int
    dim: int
    n_heads: int
    q_lora_rank: int 
    kv_lora_rank: int
    qk_nope_head_dim: int
    qk_rope_head_dim: int
    v_head_dim: int
    seq_len: int
    max_seq_len: int
    kv_cache_shape: tuple
    Q_proj_down_weight: torch.Tensor
    Q_proj_up_weight: torch.Tensor
    KV_proj_down_weight: torch.Tensor
    KV_proj_up_weight: torch.Tensor
    wo_weight: torch.Tensor

class MLA(nn.Module):
    def __init__(self, config: Config, mla_tl_kernel: tilelang.JITKernel, kernel_best_config):
        super().__init__()
        self.dim = config.dim
        self.n_heads = config.n_heads
        self.q_lora_rank = config.q_lora_rank
        self.kv_lora_rank = config.kv_lora_rank
        self.nope_head_dim = config.qk_nope_head_dim
        self.rope_head_dim = config.qk_rope_head_dim
        self.v_head_dim = config.v_head_dim
        device = "cuda"
        self.Q_proj_down = nn.Linear(self.dim, self.q_lora_rank, bias=False, dtype=torch.bfloat16, device=device)
        self.KV_proj_down = nn.Linear(self.dim, self.kv_lora_rank + self.rope_head_dim, bias=False, dtype=torch.bfloat16, device=device)

        self.Q_proj_up = nn.Linear(self.q_lora_rank, (self.nope_head_dim + self.rope_head_dim) * self.n_heads, bias=False, dtype=torch.bfloat16, device=device)
        self.KV_proj_up = nn.Linear(self.kv_lora_rank, (self.nope_head_dim + self.v_head_dim) * self.n_heads, bias=False, dtype=torch.bfloat16, device=device)

        # RoPE on half embeddings
        self.q_rope = RoPE(self.rope_head_dim)
        self.k_rope = RoPE(self.rope_head_dim)

        # Output projection
        self.wo = nn.Linear(self.v_head_dim * self.n_heads, self.dim, dtype=torch.bfloat16, bias=False, device=device)
        self.eps = 1e-6
        self.mla_tl_kernel = mla_tl_kernel
        self.kernel_best_config = kernel_best_config
   
    def forward(self, x: torch.Tensor, kv_cache: KVCache) -> torch.Tensor:
        # seq_len = 1 always here
        batch_size, seq_len, model_dim = x.size()

        q_lora = self.Q_proj_down(x)
        kv_lora = self.KV_proj_down(x)
        kv_lora, kv_len = kv_cache(kv_lora) 
        query_pos = kv_len - 1

        q_nope_and_pe = self.Q_proj_up(q_lora).view(
            batch_size, seq_len, self.n_heads, self.nope_head_dim + self.rope_head_dim).transpose(1, 2)
        q, q_pe = torch.split(q_nope_and_pe, [self.nope_head_dim, self.rope_head_dim], dim=-1)
        q_pe = self.q_rope(q_pe, start_pos=query_pos)

        kv, k_pe = torch.split(kv_lora, [self.kv_lora_rank, self.rope_head_dim], dim=-1)
        k_pe = k_pe[:, None, :, :]
        k_pe = self.k_rope(k_pe)

        KV_proj_up = self.KV_proj_up.weight.view(self.n_heads, -1, self.kv_lora_rank)
        q_absorb = KV_proj_up[:, :self.nope_head_dim, :]
        out_absorb = KV_proj_up[:, self.nope_head_dim:, :]
        q = torch.matmul(q, q_absorb)
        
        num_splits = self.kernel_best_config['num_split']
        glse = torch.zeros((batch_size, self.n_heads, num_splits), dtype=torch.float, device=x.device)
        output_partial = torch.zeros((batch_size, self.n_heads, num_splits, self.kv_lora_rank), dtype=torch.float, device=x.device)
        
        q_tl = q.view(batch_size, self.n_heads, self.kv_lora_rank)
        q_pe_tl = q_pe.view(batch_size, self.n_heads, self.rope_head_dim)
        kv_tl = kv.view(batch_size, kv_len, 1, self.kv_lora_rank).contiguous()
        k_pe_tl = k_pe.transpose(1, 2)

        tl_attn_out = torch.zeros((batch_size, self.n_heads, self.kv_lora_rank), dtype=torch.bfloat16, device=x.device)
        if kv_len < 130:
            softmax_scale = 1 / math.sqrt(self.rope_head_dim + self.nope_head_dim)
            attn_weights = (torch.matmul(q_pe, k_pe.mT) + torch.matmul(q, kv.unsqueeze(-3).mT)) * softmax_scale
            attn_weights_softmax = nn.functional.softmax(attn_weights, dim=-1, dtype=torch.float32).to(q.dtype)
            tl_attn_out = torch.einsum('bhql, blc -> bhqc', attn_weights_softmax, kv)

        else:
            tl_attn_out = self.mla_tl_kernel(
                q_tl,         
                q_pe_tl,     
                kv_tl, 
                k_pe_tl,     
                glse,
                output_partial,
            )

        tl_attn_out = tl_attn_out.view(batch_size, self.n_heads, 1, self.kv_lora_rank)
        out_absorb = out_absorb.transpose(-2, -1).contiguous()
        tl_attn_out = torch.matmul(tl_attn_out, out_absorb)
        tl_attn_out = tl_attn_out.transpose(1, 2).contiguous()
        tl_attn_out = tl_attn_out.reshape(batch_size, 1, self.n_heads * self.v_head_dim).to(torch.bfloat16)
        tl_attn_out = self.wo(tl_attn_out)
        return tl_attn_out, kv_cache.get_data() 

def custom_kernel(data: input_t) -> output_t:
    config, x, kv_cache = data
    mla_tl_kernel, kernel_best_config = get_optimal_kernel(
        batch=config.batch_size,
        heads=config.n_heads,
        kv_head_num=1,
        seqlen_kv=kv_cache.seq_len,
        dim=config.kv_lora_rank,
        pe_dim=config.qk_rope_head_dim
    )
    model = MLA(config, mla_tl_kernel, kernel_best_config)
    model.Q_proj_down.weight = nn.Parameter(config.Q_proj_down_weight)
    model.Q_proj_up.weight = nn.Parameter(config.Q_proj_up_weight)
    model.KV_proj_down.weight = nn.Parameter(config.KV_proj_down_weight)
    model.KV_proj_up.weight = nn.Parameter(config.KV_proj_up_weight)
    model.wo.weight = nn.Parameter(config.wo_weight)
    output, kv_cache = model(x, kv_cache)
    return output, kv_cache