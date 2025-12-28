#!POPCORN leaderboard amd-mla-decode
import math
from dataclasses import dataclass
import torch
from torch import nn
import torch.nn.functional as F
from task import input_t, output_t
from utils import make_match_reference

class RoPE(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.d_model = d_model
        theta = 10000 ** (-torch.arange(0, d_model//2,dtype=torch.bfloat16) / (d_model//2))
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
    def __init__(self, kv_cache_shape: tuple, **kwargs) -> None:
        super().__init__(**kwargs)
        self.register_buffer('data', torch.zeros(kv_cache_shape, dtype=torch.bfloat16))
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

import triton
import triton.language as tl
from typing import Tuple

@triton.jit
def q_proj_down_triton(
    X_ptr,             # Pointer to input tensor x [M, K]
    Wg_ptr,            # Pointer to gate weight tensor W_g [N, K]
    Indices_ptr,       # Pointer to output indices tensor [M, top_k] (int64)
    Scores_ptr,        # Pointer to output scores tensor [M, top_k]
    M,                 # Number of tokens (bs * seq_len)
    N: tl.constexpr,                 # Number of experts
    K,                 # Hidden dimension
    stride_xm, stride_xk, # Strides for X (element stride)
    stride_wn, stride_wk, # Strides for W_g (element stride)
    stride_indices_m, stride_indices_k, # Strides for Indices (element stride)
    stride_scores_m, stride_scores_k,   # Strides for Scores (element stride)
    top_k: tl.constexpr,          # Number of experts per token (compile-time constant)
    BLOCK_K: tl.constexpr,        # Tile size for K dimension
):
    """
    Triton kernel for MoE Gating: Fused Matmul(x, W_g.T) + Softmax + Iterative TopK.
    Each program instance computes the results for BLOCK_M tokens (rows in x).
    Improves Wg reuse.
    """
    pid_m = tl.program_id(axis=0)
        
# --- Compute Logits (x[pid_m, :] @ W_g.T) ---
    x_row_ptr = X_ptr + pid_m * stride_xm
    offs_k = tl.arange(0, BLOCK_K)
    offs_n = tl.arange(0, N) # Use actual N directly
    wg_ptrs = Wg_ptr + offs_n[:, None] * stride_wn + offs_k[None, :] * stride_wk

    accumulator = tl.zeros((N,), dtype=tl.float32)

    for k_start in range(0, tl.cdiv(K, BLOCK_K)):
        current_offs_k = k_start * BLOCK_K + offs_k
        x_mask = (pid_m < M) & (current_offs_k < K)
        x_chunk = tl.load(x_row_ptr + current_offs_k * stride_xk, mask=x_mask)[:, None]

        wg_mask = (current_offs_k[None, :] < K)
        wg_chunk = tl.load(wg_ptrs + k_start * BLOCK_K * stride_wk, mask=wg_mask)
        dot_result = tl.dot(wg_chunk, x_chunk)
        dot_result_reshaped = tl.reshape(dot_result, (N,)) # Shape is now [N]
        accumulator += dot_result_reshaped

    if pid_m < M:
        current_scores_fp16 = tl.softmax(accumulator.to(tl.float16)).to(tl.float16)

        scores_row_ptr = Scores_ptr + pid_m * stride_scores_m
        indices_row_ptr = Indices_ptr + pid_m * stride_indices_m

        loop_scores = current_scores_fp16
        neg_inf_fp16 = -float('inf')

        for k_iter in tl.static_range(top_k):
            max_val_fp16, max_idx = tl.max(loop_scores, axis=0, return_indices=True) # max_val_fp16 is fp16
            tl.store(indices_row_ptr + k_iter * stride_indices_k, max_idx.to(tl.int64))
            tl.store(scores_row_ptr + k_iter * stride_scores_k, max_val_fp16)
            loop_scores = tl.where(tl.arange(0, N) == max_idx, neg_inf_fp16, loop_scores)
   
def launch_q_down_proj(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Uses the Triton kernel for MoE gating (Linear + Softmax + Iterative TopK).
    x: Input tensor of shape [M, K] = [bs*seq_len, d_hidden]
    Returns: Tuple[Tensor[M, top_k], Tensor[M, top_k]] (Indices: int64, Scores: x.dtype)
    """
    x = x.contiguous()
    M, K = x.shape
    N = self.n_experts

    topk_indices = torch.empty((M, self.top_k), device=x.device, dtype=torch.int64)
    topk_scores = torch.empty((M, self.top_k), device=x.device, dtype=x.dtype)

    # --- Kernel Config ---
    BLOCK_K = 64
    grid = (M,) # One program per token
    q_proj_down_triton[grid](
        x, self.W_g, topk_indices, topk_scores,
        M, N, K,
        x.stride(0), x.stride(1),
        self.W_g.stride(0), self.W_g.stride(1),
        topk_indices.stride(0), topk_indices.stride(1),
        topk_scores.stride(0), topk_scores.stride(1),
        top_k=self.top_k,
        BLOCK_K=BLOCK_K,
        num_warps=4, # Optional tuning
        num_stages=2 # Optional tuning
    )

    return topk_indices, topk_scores

class MLA(nn.Module):
    def __init__(self, config: Config):
        super().__init__()
        self.dim = config.dim
        self.n_heads = config.n_heads
        self.q_lora_rank = config.q_lora_rank
        self.kv_lora_rank = config.kv_lora_rank
        self.nope_head_dim = config.qk_nope_head_dim
        self.rope_head_dim = config.qk_rope_head_dim
        self.v_head_dim = config.v_head_dim
        # Down-projection matrices
        self.Q_proj_down = nn.Linear(self.dim, self.q_lora_rank, dtype=torch.bfloat16, bias=False)
        self.KV_proj_down = nn.Linear(self.dim, self.kv_lora_rank + self.rope_head_dim, dtype=torch.bfloat16, bias=False)

        # Up-projection and rope projection matrices
        self.Q_proj_up = nn.Linear(self.q_lora_rank, (self.nope_head_dim + self.rope_head_dim) * self.n_heads, dtype=torch.bfloat16, bias=False)
        self.KV_proj_up = nn.Linear(self.kv_lora_rank, (self.nope_head_dim + self.v_head_dim) * self.n_heads, dtype=torch.bfloat16, bias=False)

        # RoPE on half embeddings
        self.q_rope = RoPE(self.rope_head_dim)
        self.k_rope = RoPE(self.rope_head_dim)

        # Output projection
        self.wo = nn.Linear(self.v_head_dim * self.n_heads, self.dim, dtype=torch.bfloat16, bias=False)
        self.eps = 1e-6
   
    def forward(self, x: torch.Tensor, kv_cache: KVCache) -> torch.Tensor:
        # seq_len = 1 always here
        batch_size, seq_len, model_dim = x.size()

        ################################################################################
        #                 Step 1: Handle down-projection + KV cache                    #
        ################################################################################
        q_lora = self.Q_proj_down(x)
        kv_lora = self.KV_proj_down(x)
        kv_lora, kv_len = kv_cache(kv_lora)
        query_pos = kv_len - 1

        ################################################################################
        #                  Step 2: Up-project and prepare NoPE + RoPE                  #
        ################################################################################

        # Handle queries Q first
        q_nope_and_rope = self.Q_proj_up(q_lora).view(
            batch_size, seq_len, self.n_heads, self.nope_head_dim + self.rope_head_dim)
        q_nope, q_rope = torch.split(q_nope_and_rope, [self.nope_head_dim, self.rope_head_dim], dim=-1)

        # Handle keys and values K/V. V does not need RoPE
        kv_nope, k_rope = torch.split(kv_lora, [self.kv_lora_rank, self.rope_head_dim], dim=-1)
        kv_nope = self.KV_proj_up(kv_nope).view(
            batch_size, kv_len, self.n_heads, self.nope_head_dim + self.v_head_dim)
        k_nope, v = torch.split(kv_nope, [self.nope_head_dim, self.v_head_dim], dim=-1)

        ################################################################################
        #                    Step 3: Handle RoPE Stream                                #
        ################################################################################

        # Compute RoPE for queries and combine with no-RoPE part
        q_rope = q_rope.permute(0, 2, 1, 3) # bs x n_heads x seq_len x rope_head_dim
        q_rope = self.q_rope(q_rope, start_pos=query_pos)

        q_nope = q_nope.permute(0, 2, 1, 3) # bs x n_heads x seq_len x rope_head_dim
        q = torch.concat([q_nope, q_rope], dim=-1)


        # Compute RoPE for keys and combine with no-RoPE part
        k_rope = k_rope[:, None, :, :]
        k_rope = self.k_rope(k_rope).expand(-1,self.n_heads,-1,-1)
        k_nope = k_nope.permute(0, 2, 1, 3) # bs x kv_len x n_heads x rope_head_dim
        k = torch.concat([k_nope, k_rope], dim=-1)
                
        ################################################################################
        #                        Compute Multi-head Attention                          #
        ################################################################################
        v = v.permute(0, 2, 1, 3) # bs x n_heads x kv_len x v_head_dim
        scores = torch.matmul(q, k.transpose(-1, -2)) / math.sqrt(self.rope_head_dim + self.nope_head_dim)
        attn = F.softmax(scores, dim=-1).to(torch.bfloat16)
        y = torch.matmul(attn, v).view(batch_size, 1, -1)
        y = self.wo(y)

        return y, kv_cache.get_data()


def generate_input(batchsize, dim, dq, prefill, seed):
    # Sizes derived from: https://github.com/deepseek-ai/DeepSeek-V3/blob/main/inference/model.py
    gen = torch.Generator(device='cuda')
    gen.manual_seed(seed)
    
    # Generate weights for linear layers
    Q_proj_down_weight = torch.randn((dq, dim), dtype=torch.bfloat16, generator=gen, device='cuda') / math.sqrt(dim)
    KV_proj_down_weight = torch.randn((512 + 64, dim), dtype=torch.bfloat16, generator=gen, device='cuda') / math.sqrt(dim)
    Q_proj_up_weight = torch.randn(((128 + 64) * 128, dq), dtype=torch.bfloat16, generator=gen, device='cuda') / math.sqrt(dq)
    KV_proj_up_weight = torch.randn(((128 + 128) * 128, 512), dtype=torch.bfloat16, generator=gen, device='cuda') / math.sqrt(512)
    wo_weight = torch.randn((dim, 128 * 128), dtype=torch.bfloat16, generator=gen, device='cuda') / math.sqrt(128 * 128)

    config = Config(
        batch_size=batchsize,
        dim=dim,
        q_lora_rank=dq,
        n_heads=128,
        kv_lora_rank=512,
        qk_nope_head_dim=128,
        qk_rope_head_dim=64,
        v_head_dim=128,
        seq_len=1,
        max_seq_len=8192,
        kv_cache_shape=(batchsize, 8192, 512 + 64),
        Q_proj_down_weight=Q_proj_down_weight,
        Q_proj_up_weight=Q_proj_up_weight,
        KV_proj_down_weight=KV_proj_down_weight,
        KV_proj_up_weight=KV_proj_up_weight,
        wo_weight=wo_weight,
    )
    x = torch.randn((config.batch_size, 1, config.dim), dtype=torch.bfloat16, generator=gen, device='cuda')
    
    # Pre-fill KV cache
    kv_cache = KVCache((config.batch_size, config.max_seq_len, config.kv_lora_rank + config.qk_rope_head_dim)).to('cuda')
    pre_filled_cache = torch.randn((config.batch_size, prefill, config.kv_lora_rank + config.qk_rope_head_dim), 
                                 dtype=torch.bfloat16, generator=gen, device='cuda')
    kv_cache(pre_filled_cache)

    return config, x, kv_cache

def custom_kernel(data: input_t) -> output_t:
    config, x, kv_cache = data

    # Load in model weights
    model = MLA(config).to('cuda')
    model.Q_proj_down.weight = nn.Parameter(config.Q_proj_down_weight)
    model.Q_proj_up.weight = nn.Parameter(config.Q_proj_up_weight)
    model.KV_proj_down.weight = nn.Parameter(config.KV_proj_down_weight)
    model.KV_proj_up.weight = nn.Parameter(config.KV_proj_up_weight)
    model.wo.weight = nn.Parameter(config.wo_weight)

    output, kv_cache = model(x, kv_cache)
    return output, kv_cache
