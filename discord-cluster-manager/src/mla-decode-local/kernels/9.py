import math
from dataclasses import dataclass
import torch
from torch import nn
import torch.nn.functional as F
from task import input_t, output_t


import triton
import triton.language as tl
_is_hip = True

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
        self.Q_proj_down = nn.Linear(self.dim, self.q_lora_rank, dtype=torch.bfloat16, bias=False)
        self.KV_proj_down = nn.Linear(self.dim, self.kv_lora_rank + self.rope_head_dim, dtype=torch.bfloat16, bias=False)
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

_MIN_BLOCK_KV = 32

@triton.jit
def _fwd_grouped_kernel_stage1(
    Q,
    K_Buffer,
    V_Buffer,
    sm_scale,
    kv_indptr,
    kv_indices,
    Att_Out,
    Att_Lse,
    num_kv_splits,
    stride_qbs,
    stride_qh,
    stride_buf_kbs,
    stride_buf_kh,
    stride_buf_vbs,
    stride_buf_vh,
    stride_mid_ob,
    stride_mid_oh,
    stride_mid_os,
    kv_group_num: tl.constexpr,
    q_head_num: tl.constexpr,
    BLOCK_DMODEL: tl.constexpr,
    BLOCK_DPE: tl.constexpr,
    BLOCK_DV: tl.constexpr,
    BLOCK_N: tl.constexpr,
    BLOCK_H: tl.constexpr,
    MIN_BLOCK_KV: tl.constexpr,
    logit_cap: tl.constexpr,
    Lk: tl.constexpr,
    Lv: tl.constexpr,
):
    cur_batch = tl.program_id(0)
    cur_head_id = tl.program_id(1)
    cur_kv_head = cur_head_id // tl.cdiv(kv_group_num, BLOCK_H)
    split_kv_id = tl.program_id(2)

    if BLOCK_H < kv_group_num:
        VALID_BLOCK_H: tl.constexpr = BLOCK_H
    else:
        VALID_BLOCK_H: tl.constexpr = kv_group_num
    cur_head = cur_head_id * VALID_BLOCK_H + tl.arange(0, BLOCK_H)
    mask_h = cur_head < (cur_head_id + 1) * VALID_BLOCK_H
    mask_h = mask_h & (cur_head < q_head_num)

    offs_d = tl.arange(0, BLOCK_DMODEL)
    offs_dv = tl.arange(0, BLOCK_DV)
    mask_d = offs_d < Lk
    mask_dv = offs_dv < Lv

    cur_batch_kv_start_idx = tl.load(kv_indptr + cur_batch)
    cur_batch_seq_len = tl.load(kv_indptr + cur_batch + 1) - cur_batch_kv_start_idx
    kv_splits = tl.load(num_kv_splits + cur_batch)

    offs_q = cur_batch * stride_qbs + cur_head[:, None] * stride_qh + offs_d[None, :]

    if BLOCK_DPE > 0:
        offs_dpe = BLOCK_DMODEL + tl.arange(0, BLOCK_DPE)
        mask_dpe = offs_dpe < Lk
        off_qpe = (
            cur_batch * stride_qbs + cur_head[:, None] * stride_qh + offs_dpe[None, :]
        )

    kv_len_per_split = (
        tl.cdiv(tl.cdiv(cur_batch_seq_len, kv_splits), MIN_BLOCK_KV) * MIN_BLOCK_KV
    )
    split_kv_start = kv_len_per_split * split_kv_id
    split_kv_end = tl.minimum(split_kv_start + kv_len_per_split, cur_batch_seq_len)

    e_max = tl.zeros([BLOCK_H], dtype=tl.float32) - float("inf")
    e_sum = tl.zeros([BLOCK_H], dtype=tl.float32)
    acc = tl.zeros([BLOCK_H, BLOCK_DV], dtype=tl.float32)

    if split_kv_end > split_kv_start:
        q = tl.load(Q + offs_q, mask=(mask_h[:, None]) & (mask_d[None, :]), other=0.0)
        if BLOCK_DPE > 0:
            qpe = tl.load(
                Q + off_qpe, mask=(mask_h[:, None]) & (mask_dpe[None, :]), other=0.0
            )
        for start_n in range(split_kv_start, split_kv_end, BLOCK_N):
            offs_n = start_n + tl.arange(0, BLOCK_N)
            kv_loc = tl.load(
                kv_indices + cur_batch_kv_start_idx + offs_n,
                mask=offs_n < split_kv_end,
                other=0,
            )
            offs_buf_k = (
                kv_loc[None, :] * stride_buf_kbs
                + cur_kv_head * stride_buf_kh
                + offs_d[:, None]
            )
            k = tl.load(
                K_Buffer + offs_buf_k,
                mask=(offs_n[None, :] < split_kv_end) & (mask_d[:, None]),
                other=0.0,
            )
            qk = tl.dot(q, k.to(q.dtype))
            if BLOCK_DPE > 0:
                offs_buf_kpe = (
                    kv_loc[None, :] * stride_buf_kbs
                    + cur_kv_head * stride_buf_kh
                    + offs_dpe[:, None]
                )
                kpe = tl.load(
                    K_Buffer + offs_buf_kpe,
                    mask=(offs_n[None, :] < split_kv_end) & (mask_dpe[:, None]),
                    other=0.0,
                )
                qk += tl.dot(qpe, kpe.to(qpe.dtype))
            qk *= sm_scale

            if logit_cap > 0:
                qk = logit_cap * tanh(qk / logit_cap)

            qk = tl.where(
                mask_h[:, None] & (offs_n[None, :] < split_kv_end), qk, float("-inf")
            )

            offs_buf_v = (
                kv_loc[:, None] * stride_buf_vbs
                + cur_kv_head * stride_buf_vh
                + offs_dv[None, :]
            )
            v = tl.load(
                V_Buffer + offs_buf_v,
                mask=(offs_n[:, None] < split_kv_end) & (mask_dv[None, :]),
                other=0.0,
            )

            n_e_max = tl.maximum(tl.max(qk, 1), e_max)
            re_scale = tl.exp(e_max - n_e_max)
            p = tl.exp(qk - n_e_max[:, None])
            acc *= re_scale[:, None]
            acc += tl.dot(p.to(v.dtype), v)

            e_sum = e_sum * re_scale + tl.sum(p, 1)
            e_max = n_e_max

        offs_mid_o = (
            cur_batch * stride_mid_ob
            + cur_head[:, None] * stride_mid_oh
            + split_kv_id * stride_mid_os
            + offs_dv[None, :]
        )

        tl.store(
            Att_Out + offs_mid_o,
            acc / e_sum[:, None],
            mask=(mask_h[:, None]) & (mask_dv[None, :]),
        )

        offs_mid_o_1 = (
            cur_batch * stride_mid_ob
            + cur_head * stride_mid_oh
            + split_kv_id * stride_mid_os
        ) // Lv

        tl.store(
            Att_Lse + offs_mid_o_1,
            e_max + tl.log(e_sum),
            mask=mask_h,
        )

def _decode_grouped_att_m_fwd(
    q,
    k_buffer,
    v_buffer,
    att_out,
    att_lse,
    kv_indptr,
    kv_indices,
    num_kv_splits,
    max_kv_splits,
    sm_scale,
    logit_cap,
):
    BLOCK = 32
    Lk = k_buffer.shape[-1]
    Lv = v_buffer.shape[-1]

    # [TODO] work around shmem limit on MI3xx
    if _is_hip and Lk >= 576:
        BLOCK = 16

    if Lk == 576:
        BLOCK_DMODEL = 512
        BLOCK_DPE = 64
    elif Lk == 288:
        BLOCK_DMODEL = 256
        BLOCK_DPE = 32
    else:
        BLOCK_DMODEL = triton.next_power_of_2(Lk)
        BLOCK_DPE = 0
    BLOCK_DV = triton.next_power_of_2(Lv)

    batch, head_num = kv_indptr.shape[0] - 1, q.shape[1]
    kv_group_num = q.shape[1] // k_buffer.shape[1]

    BLOCK_H = 16
    MAX_KV_SPLITS = max_kv_splits
    grid = (
        batch,
        triton.cdiv(head_num, min(BLOCK_H, kv_group_num)),
        MAX_KV_SPLITS,
    )

    extra_kargs = {}
    num_stages = 2

    if _is_hip:
        # https://rocm.docs.amd.com/en/docs-6.2.0/how-to/llm-fine-tuning-optimization/optimizing-triton-kernel.html
        # https://github.com/triton-lang/triton/blob/main/third_party/amd/backend/compiler.py
        extra_kargs = {"waves_per_eu": 1, "matrix_instr_nonkdim": 16, "kpack": 2}
        num_stages = 1

    _fwd_grouped_kernel_stage1[grid](
        q,
        k_buffer,
        v_buffer,
        sm_scale,
        kv_indptr,
        kv_indices,
        att_out,
        att_lse,
        num_kv_splits,
        q.stride(0),
        q.stride(1),
        k_buffer.stride(0),
        k_buffer.stride(1),
        v_buffer.stride(0),
        v_buffer.stride(1),
        att_out.stride(0),
        att_out.stride(1),
        att_out.stride(2),
        kv_group_num=kv_group_num,
        q_head_num=head_num,
        BLOCK_DMODEL=BLOCK_DMODEL,
        BLOCK_DPE=BLOCK_DPE,
        BLOCK_DV=BLOCK_DV,
        BLOCK_N=BLOCK,
        BLOCK_H=BLOCK_H,
        MIN_BLOCK_KV=_MIN_BLOCK_KV,
        logit_cap=logit_cap,
        num_warps=4,
        num_stages=num_stages,
        Lk=Lk,
        Lv=Lv,
        **extra_kargs,
    )




@triton.jit
def _fwd_kernel_stage2(
    Mid_O,
    Mid_O_1,
    O,
    kv_indptr,
    num_kv_splits,
    stride_mid_ob,
    stride_mid_oh,
    stride_mid_os,
    stride_obs,
    stride_oh,
    MAX_KV_SPLITS: tl.constexpr,
    MIN_BLOCK_KV: tl.constexpr,
    BLOCK_DV: tl.constexpr,
    Lv: tl.constexpr,
):
    cur_batch = tl.program_id(0)
    cur_head = tl.program_id(1)

    cur_batch_seq_len = tl.load(kv_indptr + cur_batch + 1) - tl.load(
        kv_indptr + cur_batch
    )
    kv_splits = tl.load(num_kv_splits + cur_batch)

    offs_d = tl.arange(0, BLOCK_DV)
    mask_d = offs_d < Lv

    e_sum = 0.0
    e_max = -float("inf")
    acc = tl.zeros([BLOCK_DV], dtype=tl.float32)

    offs_v = cur_batch * stride_mid_ob + cur_head * stride_mid_oh + offs_d
    offs_logic = (cur_batch * stride_mid_ob + cur_head * stride_mid_oh) // Lv
    kv_len_per_split = (
        tl.cdiv(tl.cdiv(cur_batch_seq_len, kv_splits), MIN_BLOCK_KV) * MIN_BLOCK_KV
    )

    for split_kv_id in range(0, MAX_KV_SPLITS):
        split_kv_start = kv_len_per_split * split_kv_id
        split_kv_end = tl.minimum(split_kv_start + kv_len_per_split, cur_batch_seq_len)

        if split_kv_end > split_kv_start:
            tv = tl.load(
                Mid_O + offs_v + split_kv_id * stride_mid_os, mask=mask_d, other=0.0
            )
            tlogic = tl.load(Mid_O_1 + offs_logic + split_kv_id * stride_mid_os // Lv)
            n_e_max = tl.maximum(tlogic, e_max)

            old_scale = tl.exp(e_max - n_e_max)
            acc *= old_scale
            exp_logic = tl.exp(tlogic - n_e_max)
            acc += exp_logic * tv

            e_sum = e_sum * old_scale + exp_logic
            e_max = n_e_max

    tl.store(
        O + cur_batch * stride_obs + cur_head * stride_oh + offs_d,
        acc / e_sum,
        mask=mask_d,
    )


def _decode_softmax_reducev_fwd(
    logits,
    lse,
    q,
    o,
    v_buffer,
    kv_indptr,
    num_kv_splits,
    max_kv_splits,
):
    batch, head_num = q.shape[0], q.shape[1]
    Lv = v_buffer.shape[-1]
    BLOCK_DV = triton.next_power_of_2(Lv)

    MAX_KV_SPLITS = max_kv_splits

    extra_kargs = {}
    if _is_hip:
        # https://rocm.docs.amd.com/en/docs-6.2.0/how-to/llm-fine-tuning-optimization/optimizing-triton-kernel.html
        # https://github.com/triton-lang/triton/blob/main/third_party/amd/backend/compiler.py
        extra_kargs = {"waves_per_eu": 4, "matrix_instr_nonkdim": 16, "kpack": 2}

    grid = (batch, head_num)
    _fwd_kernel_stage2[grid](
        logits,
        lse,
        o,
        kv_indptr,
        num_kv_splits,
        logits.stride(0),
        logits.stride(1),
        logits.stride(2),
        o.stride(0),
        o.stride(1),
        MAX_KV_SPLITS=MAX_KV_SPLITS,
        MIN_BLOCK_KV=_MIN_BLOCK_KV,
        BLOCK_DV=BLOCK_DV,
        Lv=Lv,
        num_warps=4,
        num_stages=2,
        **extra_kargs,
    )



def decode_attention_fwd_grouped(
    q,
    k_buffer,
    v_buffer,
    o,
    kv_indptr,
    kv_indices,
    attn_logits,
    attn_lse,
    num_kv_splits,
    max_kv_splits,
    sm_scale,
    logit_cap=0.0,
):
    _decode_grouped_att_m_fwd(
        q,
        k_buffer,
        v_buffer,
        attn_logits,
        attn_lse,
        kv_indptr,
        kv_indices,
        num_kv_splits,
        max_kv_splits,
        sm_scale,
        logit_cap,
    )

    _decode_softmax_reducev_fwd(
        attn_logits,
        attn_lse,
        q,
        o,
        v_buffer,
        kv_indptr,
        num_kv_splits,
        max_kv_splits,
    )

class PengcuoMLA(nn.Module):
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
        self.Q_proj_down_weight = None
        # self.Q_proj_down = nn.Linear(self.dim, self.q_lora_rank, dtype=torch.bfloat16, bias=False)
        self.KV_proj_down_weight = None
        # self.KV_proj_down = nn.Linear(self.dim, self.kv_lora_rank + self.rope_head_dim, dtype=torch.bfloat16, bias=False)

        # Up-projection and rope projection matrices
        self.Q_proj_up_weight = None
        # self.Q_proj_up = nn.Linear(self.q_lora_rank, (self.nope_head_dim + self.rope_head_dim) * self.n_heads, dtype=torch.bfloat16, bias=False)
        self.KV_proj_up_weight = None
        # self.KV_proj_up = nn.Linear(self.kv_lora_rank, (self.nope_head_dim + self.v_head_dim) * self.n_heads, dtype=torch.bfloat16, bias=False)

        # RoPE on half embeddings
        self.q_rope = RoPE(self.rope_head_dim)
        self.k_rope = RoPE(self.rope_head_dim)

        # Output projection
        self.wo_weight = None
        # self.wo = nn.Linear(self.v_head_dim * self.n_heads, self.dim, dtype=torch.bfloat16, bias=False)
        self.eps = 1e-6
   
    def forward(self, x: torch.Tensor, kv_cache: KVCache) -> torch.Tensor:
        batch_size, seq_len, model_dim = x.size()

        ################################################################################
        #                 Step 1: Handle down-projection + KV cache                    #
        ################################################################################
        # q_lora = self.Q_proj_down(x)
        q_lora = x @ self.Q_proj_down_weight.T
        # kv_lora = self.KV_proj_down(x)
        kv_lora = x @ self.KV_proj_down_weight.T
        kv_lora, kv_len = kv_cache(kv_lora)
        query_pos = kv_len - 1

        ################################################################################
        #                  Step 2: Up-project and prepare NoPE + RoPE                  #
        ################################################################################
        q_nope_and_rope = (q_lora @ self.Q_proj_up_weight.T).view(
            batch_size, seq_len, self.n_heads, self.nope_head_dim + self.rope_head_dim)
        q_nope, q_rope = torch.split(q_nope_and_rope, [self.nope_head_dim, self.rope_head_dim], dim=-1)

        # Handle keys and values K/V. V does not need RoPE
        kv_nope, k_rope = torch.split(kv_lora, [self.kv_lora_rank, self.rope_head_dim], dim=-1)

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
        k_rope = self.k_rope(k_rope)

        kv_up_weight = self.KV_proj_up_weight.view(self.n_heads, self.nope_head_dim + self.v_head_dim, -1)
        w_kc = kv_up_weight[:, :self.nope_head_dim, :]
        w_vc = kv_up_weight[:, self.nope_head_dim:, :]
        w_vc = w_vc.permute(0, 2, 1)

        # mla_input_nope = q_nope @ w_kc
        q_nope = q_nope.squeeze(2)
        # b h d --> h b d
        q_nope = q_nope.permute(1, 0, 2)
        mla_input_nope = q_nope @ w_kc
        mla_input_nope = mla_input_nope.permute(1, 0, 2).view(batch_size, self.n_heads, 1, -1)
        
        mla_q_input = torch.concat([mla_input_nope, q_rope], dim=-1)
        mla_k_input = kv_lora.clone().unsqueeze(1)
        mla_k_input[..., self.kv_lora_rank:] = k_rope

        flash_mla_k_buf = mla_k_input
        flash_mla_q = mla_q_input.view(batch_size, self.n_heads, -1)

        total_tokens = batch_size * kv_len
        k_buffer = flash_mla_k_buf.squeeze(1).reshape(-1, 1, self.kv_lora_rank + self.rope_head_dim)
        v_buffer = k_buffer[..., :self.kv_lora_rank]

        flash_output = torch.zeros(batch_size, self.n_heads, self.kv_lora_rank, dtype=x.dtype, device="cuda")

        b_seq_len = torch.full((batch_size,), kv_len, device="cuda")
        kv_indptr = torch.zeros((batch_size + 1,), dtype=torch.int32, device="cuda")
        kv_indptr[1 : batch_size + 1] = torch.cumsum(b_seq_len[:batch_size], dim=0)
        kv_indices = torch.arange(total_tokens, device="cuda")

        max_kv_splits = 8
        num_kv_splits = torch.full((batch_size,), 1, dtype=torch.int32, device="cuda")
        attn_logits1 = torch.empty(
            (batch_size, self.n_heads, max_kv_splits, self.kv_lora_rank),
            dtype=torch.float32,
            device="cuda",
        )
        attn_lse1 = torch.empty(
            (batch_size, self.n_heads, max_kv_splits, self.kv_lora_rank),
            dtype=torch.float32,
            device="cuda",
        )

        sm_scale = 1.0 / math.sqrt(self.rope_head_dim + self.nope_head_dim)
        decode_attention_fwd_grouped(
            flash_mla_q,
            k_buffer,
            v_buffer,
            flash_output,
            kv_indptr,
            kv_indices,
            attn_logits1,
            attn_lse1,
            num_kv_splits,
            max_kv_splits,
            sm_scale,
        )
        # flash_output = flash_output.unsqueeze(2)
        # mla_out = flash_output @ w_vc
        # mla_out = mla_out.view(batch_size, 1, -1)
        # mla_out = mla_out @ self.wo_weight.T

        flash_output = flash_output.permute(1, 0, 2)
        # h, b, 128 = h, b, 512 @ h, 512, 128
        mla_out = flash_output @ w_vc

        # h, b, 7168 = h, b, 128 @ h, 128 7168
        mla_out = mla_out @ self.wo_weight.T.view(-1, 128, 7168)
        
        # h, b, 7168 => b, 1 7168
        mla_out = torch.sum(mla_out, dim=0)
        mla_out = mla_out.view(batch_size, 1, -1)

        return mla_out, kv_cache.get_data()

def custom_kernel(data: input_t) -> output_t:
    config, x, kv_cache = data

    model = PengcuoMLA(config).to('cuda')
    model.Q_proj_down_weight = config.Q_proj_down_weight
    model.Q_proj_up_weight = config.Q_proj_up_weight
    model.KV_proj_down_weight = config.KV_proj_down_weight
    model.KV_proj_up_weight = config.KV_proj_up_weight
    model.wo_weight = config.wo_weight

    output, kv_cache = model(x, kv_cache)
    return output, kv_cache