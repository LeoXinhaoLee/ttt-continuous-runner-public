#!POPCORN leaderboard amd-mla-decode

# This is a submission template for popcorn leaderboard 'amd-mla-decode'.
# Your task is as follows:
# > You will implement a custom mla decode kernel optimized for MI300, a few things simplified here:
# >
# > 1. Q, K, V data type as bfloat16
# >
# > 2. decode only with pre-allocated non-paged latent kv cache
# >
# > 3. return the update kv cache with MLA output
# >
# > The shapes of all outer and inner dimensions of tensors are from DeepSeek-R1, and split number of heads to fit in one GPU.
# > To be explicit, you will be given a tuple to tensors:
# >
# > ```yml
# > input [bs, sq, dim]
# > attn_output [bs, n_heads, sq, v_head_dim]
# > kv_cache [bs, sq, kv_lora_rank + qk_rope_head_dim]
# > ```
# >
# > where
# >
# > 0. bs::128 # batch size
# > 1. prefill::[512, 2048, 4096, 6144] # as kv length
# > 2. sq::1 # as only consider decoding
# > 3. dim::7168 # hidden size of deepseek v3
# > 4. kv_lora_rank::[512] # kv lora rank of deepseek v3
# > 5. qk_rope_head_dim::[64] # rope embedding dimension
# > 6. v_head_dim::128 # head size
# > 7. n_heads::128 # num of attn heads
# >
# > The ranking criteria is the geometric mean of the benchmark results.
# >
# > For the grand prize, your kernel will be evaluated against the speed of light analysis
# > and the solution closest to the speed of light will be awarded the grand prize.
# >
# > The speed of light analysis is::
# > | bs | prefill | sq | dtype |  roofline time(us) |
# > |---|---|---|---|---|
# > | 128 | 512 | 1 | bf16 | 54.62 |
# > | 128 | 2048 | 1 | bf16 | 141.16 |
# > | 128 | 4096 | 1 | bf16 | 210.75 |
# > | 128 | 6144 | 1 | bf16 | 280.87 |
# The deadline for this leaderboard is 2025-06-02 00:00:00+00:00

# You can automatically route this file to specific GPUs by adding a line
# `#!POPCORN gpus <GPUs>` to the header of this file.
# Happy hacking!

import math
from dataclasses import dataclass
import torch
from torch import nn
import torch.nn.functional as F
from task import input_t, output_t


class RoPE(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.d_model = d_model
        theta = 10000 ** (
            -torch.arange(0, d_model // 2, dtype=torch.bfloat16) / (d_model // 2)
        )
        self.register_buffer("theta", theta)

    def rotate_half(self, x: torch.Tensor) -> torch.Tensor:
        x1, x2 = x.chunk(2, dim=-1)
        return torch.cat((-x2, x1), dim=-1)

    def forward(self, x: torch.Tensor, start_pos: int = 0) -> torch.Tensor:
        seq_len = x.size(-2)
        d_model = x.size(-1)
        assert d_model == self.d_model
        seq_idx = torch.arange(start_pos, start_pos + seq_len, device=x.device)
        idx_theta = torch.einsum("s,d->sd", seq_idx, self.theta)
        idx_theta2 = torch.cat([idx_theta, idx_theta], dim=-1)
        cos = idx_theta2.cos().to(torch.bfloat16)
        sin = idx_theta2.sin().to(torch.bfloat16)
        return x * cos + self.rotate_half(x) * sin


class KVCache(nn.Module):
    def __init__(self, kv_cache_shape: tuple) -> None:
        super().__init__()
        self.register_buffer(
            "data", torch.zeros(kv_cache_shape, dtype=torch.bfloat16, device="cuda")
        )
        self.seq_len = 0
        self.zero()

    def zero(self) -> None:
        self.data.zero_()

    def get_data(self) -> torch.Tensor:
        return self.data

    def forward(self, c_kv: torch.Tensor) -> torch.Tensor:
        assert self.seq_len + c_kv.size(1) <= self.data.size(1), "KV Cache Exceeded"

        self.data = self.data.to(c_kv.dtype)
        self.data[:, self.seq_len : self.seq_len + c_kv.size(1), :] = c_kv
        self.seq_len += c_kv.size(1)

        return self.data[:, : self.seq_len], self.seq_len


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


# Preallocate big memory. Is it OK?
tmp = torch.zeros(128 * 6200 * 32768, dtype=torch.bfloat16, device="cuda")


class MLA(nn.Module):
    def __init__(self, config: Config, kv_len: int):
        super().__init__()
        self.dim = config.dim
        self.n_heads = config.n_heads
        self.q_lora_rank = config.q_lora_rank
        self.kv_lora_rank = config.kv_lora_rank
        self.nope_head_dim = config.qk_nope_head_dim
        self.rope_head_dim = config.qk_rope_head_dim
        self.v_head_dim = config.v_head_dim
        # Down-projection matrices
        self.Q_proj_down = config.Q_proj_down_weight
        self.KV_proj_down = config.KV_proj_down_weight

        # Up-projection and rope projection matrices
        self.Q_proj_up = config.Q_proj_up_weight
        self.KV_proj_up = config.KV_proj_up_weight

        # RoPE on half embeddings
        self.q_rope = RoPE(self.rope_head_dim)
        self.k_rope = RoPE(self.rope_head_dim)

        # Output projection
        self.wo = config.wo_weight
        self.eps = 1e-6

        tmp_shape = (
            config.batch_size,
            kv_len + 1,
            self.n_heads * (self.nope_head_dim + self.v_head_dim),
        )

        self.tmp = tmp[
            : config.batch_size * (kv_len + 1) * (self.n_heads * (self.nope_head_dim + self.v_head_dim))
        ].view(tmp_shape)


    def forward(self, x: torch.Tensor, kv_cache: KVCache) -> torch.Tensor:
        # seq_len = 1 always here
        batch_size, seq_len, model_dim = x.size()

        ################################################################################
        #                 Step 1: Handle down-projection + KV cache                    #
        ################################################################################
        q_lora = F.linear(x, self.Q_proj_down)
        kv_lora = F.linear(x, self.KV_proj_down)
        kv_lora, kv_len = kv_cache(kv_lora)
        query_pos = kv_len - 1

        ################################################################################
        #                  Step 2: Up-project and prepare NoPE + RoPE                  #
        ################################################################################

        # Handle queries Q first
        q_nope_and_rope = F.linear(q_lora, self.Q_proj_up).view(
            batch_size, seq_len, self.n_heads, self.nope_head_dim + self.rope_head_dim
        )
        q_nope, q_rope = torch.split(
            q_nope_and_rope, [self.nope_head_dim, self.rope_head_dim], dim=-1
        )

        # Handle keys and values K/V. V does not need RoPE
        kv_nope, k_rope = torch.split(
            kv_lora, [self.kv_lora_rank, self.rope_head_dim], dim=-1
        )

        #print(
            #f"kv_nope shape: {kv_nope.shape}, KV_proj_up shape: {self.KV_proj_up.shape}"
        #)

        torch.matmul(kv_nope, self.KV_proj_up.T, out=self.tmp)
        kv_nope = self.tmp.view(
            batch_size, kv_len, self.n_heads, self.nope_head_dim + self.v_head_dim
        )

        """
        kv_nope = F.linear(kv_nope, self.KV_proj_up).view(
            batch_size, kv_len, self.n_heads, self.nope_head_dim + self.v_head_dim
        )
        """

        # print(kv_nope.dtype)

        k_nope, v = torch.split(kv_nope, [self.nope_head_dim, self.v_head_dim], dim=-1)

        ################################################################################
        #                    Step 3: Handle RoPE Stream                                #
        ################################################################################

        # Compute RoPE for queries and combine with no-RoPE part
        q_rope = q_rope.permute(0, 2, 1, 3)  # bs x n_heads x seq_len x rope_head_dim
        q_rope = self.q_rope(q_rope, start_pos=query_pos)

        q_nope = q_nope.permute(0, 2, 1, 3)  # bs x n_heads x seq_len x rope_head_dim
        q = torch.concat([q_nope, q_rope], dim=-1)

        # Compute RoPE for keys and combine with no-RoPE part
        k_rope = k_rope[:, None, :, :]
        k_rope = self.k_rope(k_rope).expand(-1, self.n_heads, -1, -1)
        k_nope = k_nope.permute(0, 2, 1, 3)  # bs x kv_len x n_heads x rope_head_dim
        k = torch.concat([k_nope, k_rope], dim=-1)

        ################################################################################
        #                        Compute Multi-head Attention                          #
        ################################################################################
        v = v.permute(0, 2, 1, 3)  # bs x n_heads x kv_len x v_head_dim
        scores = torch.matmul(q, k.transpose(-1, -2)) / math.sqrt(
            self.rope_head_dim + self.nope_head_dim
        )
        attn = F.softmax(scores, dim=-1).to(torch.bfloat16)
        y = torch.matmul(attn, v).view(batch_size, 1, -1)
        y = F.linear(y, self.wo)

        return y, kv_cache.get_data()


import os


def custom_run(data: input_t) -> output_t:
    config, x, kv_cache = data
    model = MLA(config, kv_cache.seq_len).to("cuda")

    output, kv_cache = model(x, kv_cache)
    return output, kv_cache


def custom_kernel(data: input_t) -> output_t:
    if "PROFILE" in os.environ:
        from torch.profiler import profile, record_function, ProfilerActivity

        with profile(
            activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA],
            record_shapes=True,
            with_stack=True,
        ) as prof:
            ret = custom_run(data)
        # print(prof.key_averages().table(sort_by="cuda_time_total"))
        prof.export_chrome_trace("trace.json")
        return ret
    else:
        return custom_run(data)
