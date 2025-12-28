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
        self.Q_proj_down = nn.Linear(self.dim, self.q_lora_rank, bias=False, dtype=torch.bfloat16)
        self.KV_proj_down = nn.Linear(self.dim, self.kv_lora_rank + self.rope_head_dim, bias=False, dtype=torch.bfloat16)

        # Up-projection and rope projection matrices
        self.Q_proj_up = nn.Linear(self.q_lora_rank, (self.nope_head_dim + self.rope_head_dim) * self.n_heads, bias=False, dtype=torch.bfloat16)
        self.KV_proj_up = nn.Linear(self.kv_lora_rank, (self.nope_head_dim + self.v_head_dim) * self.n_heads, bias=False, dtype=torch.bfloat16)

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

def custom_kernel(data: input_t) -> output_t:
    config, x, kv_cache = data
    
    # Extract dimensions
    batch_size, seq_len, model_dim = x.size()
    
    # Get weights - use direct tensor operations for speed
    Q_down_w = config.Q_proj_down_weight
    Q_up_w = config.Q_proj_up_weight
    KV_down_w = config.KV_proj_down_weight
    KV_up_w = config.KV_proj_up_weight
    wo_w = config.wo_weight
    
    n_heads = config.n_heads
    q_lora_rank = config.q_lora_rank
    kv_lora_rank = config.kv_lora_rank
    nope_head_dim = config.qk_nope_head_dim
    rope_head_dim = config.qk_rope_head_dim
    v_head_dim = config.v_head_dim
    
    ################################################################################
    #                 Step 1: Optimized down-projection + KV cache                 #
    ################################################################################
    
    # Use direct matrix multiplication (faster than nn.Linear)
    x_reshaped = x.view(-1, model_dim)
    
    q_lora = torch.mm(x_reshaped, Q_down_w.T).view(batch_size, seq_len, q_lora_rank)
    kv_lora_new = torch.mm(x_reshaped, KV_down_w.T).view(batch_size, seq_len, kv_lora_rank + rope_head_dim)
    
    # Update KV cache
    kv_lora_full, kv_len = kv_cache(kv_lora_new)
    query_pos = kv_len - 1
    
    ################################################################################
    #                  Step 2: Optimized up-projections                            #
    ################################################################################
    
    # Q up-projection
    q_lora_flat = q_lora.view(-1, q_lora_rank)
    q_nope_and_rope = torch.mm(q_lora_flat, Q_up_w.T).view(
        batch_size, seq_len, n_heads, nope_head_dim + rope_head_dim)
    q_nope, q_rope = torch.split(q_nope_and_rope, [nope_head_dim, rope_head_dim], dim=-1)
    
    # Split KV cache
    kv_nope_full, k_rope_full = torch.split(kv_lora_full, [kv_lora_rank, rope_head_dim], dim=-1)
    
    # KV up-projection
    kv_nope_flat = kv_nope_full.contiguous().view(-1, kv_lora_rank)
    kv_nope_up = torch.mm(kv_nope_flat, KV_up_w.T).view(
        batch_size, kv_len, n_heads, nope_head_dim + v_head_dim)
    k_nope, v = torch.split(kv_nope_up, [nope_head_dim, v_head_dim], dim=-1)
    
    ################################################################################
    #                    Step 3: RoPE computation (matching reference exactly)      #
    ################################################################################
    
    # Create RoPE objects to match reference implementation exactly
    q_rope_module = RoPE(rope_head_dim)
    k_rope_module = RoPE(rope_head_dim)
    
    # Move theta to correct device and dtype
    theta = 10000 ** (-torch.arange(0, rope_head_dim//2, dtype=torch.bfloat16, device=x.device) / (rope_head_dim//2))
    q_rope_module.theta = theta
    k_rope_module.theta = theta
    
    # Apply RoPE to queries (exactly like reference)
    q_rope_perm = q_rope.permute(0, 2, 1, 3)  # bs x n_heads x seq_len x rope_head_dim
    q_rope_rotated = q_rope_module(q_rope_perm, start_pos=query_pos)
    
    q_nope_perm = q_nope.permute(0, 2, 1, 3)  # bs x n_heads x seq_len x nope_head_dim
    q_full = torch.concat([q_nope_perm, q_rope_rotated], dim=-1)
    
    # Apply RoPE to keys (exactly like reference)
    k_rope_expanded = k_rope_full[:, None, :, :]  # Add head dimension
    k_rope_rotated = k_rope_module(k_rope_expanded).expand(-1, n_heads, -1, -1)
    k_nope_perm = k_nope.permute(0, 2, 1, 3)  # bs x n_heads x kv_len x nope_head_dim
    k_full = torch.concat([k_nope_perm, k_rope_rotated], dim=-1)
    
    ################################################################################
    #                    Step 4: Attention computation                              #
    ################################################################################
    
    v_perm = v.permute(0, 2, 1, 3)  # bs x n_heads x kv_len x v_head_dim
    
    # Compute scores with exact same scaling as reference
    head_dim = rope_head_dim + nope_head_dim
    scores = torch.matmul(q_full, k_full.transpose(-1, -2)) / math.sqrt(head_dim)
    attn = F.softmax(scores, dim=-1).to(torch.bfloat16)
    
    # Apply attention
    y = torch.matmul(attn, v_perm).view(batch_size, seq_len, -1)
    
    # Output projection
    y_flat = y.view(-1, n_heads * v_head_dim)
    output = torch.mm(y_flat, wo_w.T).view(batch_size, seq_len, model_dim)
    
    return output, kv_cache.get_data()