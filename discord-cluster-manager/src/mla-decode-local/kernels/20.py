import math
import torch
from torch import nn
import torch.nn.functional as F
from typing import Tuple

class RoPE(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.d_model = d_model
        theta = 10000 ** (-torch.arange(0, d_model//2, dtype=torch.bfloat16) / (d_model//2))
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

    def forward(self, c_kv: torch.Tensor) -> Tuple[torch.Tensor, int]:
        assert self.seq_len + c_kv.size(1) <= self.data.size(1), "KV Cache max"
        
        self.data = self.data.to(c_kv.dtype)
        self.data[:, self.seq_len : self.seq_len + c_kv.size(1), :] = c_kv
        self.seq_len += c_kv.size(1)
        
        return self.data[:, :self.seq_len], self.seq_len

class OptimizedMLA(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.dim = config.dim
        self.n_heads = config.n_heads
        self.q_lora_rank = config.q_lora_rank
        self.kv_lora_rank = config.kv_lora_rank
        self.nope_head_dim = config.qk_nope_head_dim
        self.rope_head_dim = config.qk_rope_head_dim
        self.v_head_dim = config.v_head_dim

        self.Q_proj_down = nn.Linear(self.dim, self.q_lora_rank, dtype=torch.bfloat16, bias=False)
        self.KV_proj_down = nn.Linear(self.dim, self.kv_lora_rank + self.rope_head_dim, dtype=torch.bfloat16, bias=False)
        self.Q_proj_up = nn.Linear(self.q_lora_rank, (self.nope_head_dim + self.rope_head_dim) * self.n_heads, dtype=torch.bfloat16, bias=False)
        self.KV_proj_up = nn.Linear(self.kv_lora_rank, (self.nope_head_dim + self.v_head_dim) * self.n_heads, dtype=torch.bfloat16, bias=False)
        self.wo = nn.Linear(self.v_head_dim * self.n_heads, self.dim, dtype=torch.bfloat16, bias=False)

        self.q_rope = RoPE(self.rope_head_dim)
        self.k_rope = RoPE(self.rope_head_dim)
        
        self.eps = 1e-6

    def forward(self, x: torch.Tensor, kv_cache: KVCache) -> Tuple[torch.Tensor, torch.Tensor]:
        batch_size, seq_len, model_dim = x.size()

        q_lora = self.Q_proj_down(x)
        kv_lora = self.KV_proj_down(x)
        kv_lora, kv_len = kv_cache(kv_lora)
        query_pos = kv_len - 1

        q_nope_and_rope = self.Q_proj_up(q_lora).view(
            batch_size, seq_len, self.n_heads, self.nope_head_dim + self.rope_head_dim)
        q_nope, q_rope = torch.split(q_nope_and_rope, [self.nope_head_dim, self.rope_head_dim], dim=-1)

        kv_nope, k_rope = torch.split(kv_lora, [self.kv_lora_rank, self.rope_head_dim], dim=-1)
        kv_nope = self.KV_proj_up(kv_nope).view(
            batch_size, kv_len, self.n_heads, self.nope_head_dim + self.v_head_dim)
        k_nope, v = torch.split(kv_nope, [self.nope_head_dim, self.v_head_dim], dim=-1)

        q_rope = q_rope.reshape(batch_size, self.n_heads, seq_len, self.rope_head_dim)
        q_rope = self.q_rope(q_rope, start_pos=query_pos)
        q_rope = q_rope.reshape(batch_size, seq_len, self.n_heads, self.rope_head_dim)
        q = torch.concat([q_nope, q_rope], dim=-1)

        k_rope = k_rope[:, :, None, :]
        k_rope = self.k_rope(k_rope).expand(-1, -1, self.n_heads, -1)
        k = torch.concat([k_nope, k_rope], dim=-1)

        q = q.reshape(batch_size, self.n_heads, 1, self.rope_head_dim + self.nope_head_dim)
        k = k.reshape(batch_size, self.n_heads, kv_len, self.rope_head_dim + self.nope_head_dim)
        v = v.reshape(batch_size, self.n_heads, -1, self.v_head_dim)
        
        scores = torch.matmul(q, k.transpose(-1, -2)) / math.sqrt(self.rope_head_dim + self.nope_head_dim)
        attn = F.softmax(scores, dim=-1).to(torch.bfloat16)
        y = torch.matmul(attn, v).view(batch_size, 1, -1)
        y = self.wo(y)

        return y, kv_cache.get_data()

def custom_kernel(data: Tuple) -> Tuple[torch.Tensor, torch.Tensor]:
    config, x, kv_cache = data
    
    model = OptimizedMLA(config).to(x.device)
    
    model.Q_proj_down.weight = nn.Parameter(config.Q_proj_down_weight)
    model.Q_proj_up.weight = nn.Parameter(config.Q_proj_up_weight)
    model.KV_proj_down.weight = nn.Parameter(config.KV_proj_down_weight)
    model.KV_proj_up.weight = nn.Parameter(config.KV_proj_up_weight)
    model.wo.weight = nn.Parameter(config.wo_weight)
    
    with torch.cuda.amp.autocast(enabled=False):
        output, updated_kv = model(x, kv_cache)
    
    return output, updated_kv