from __future__ import annotations

import os
from datetime import timedelta

import torch
import torch.distributed as dist


local_rank = int(os.environ["LOCAL_RANK"])
torch.cuda.set_device(local_rank)
device = torch.device("cuda", local_rank)
dist.init_process_group("nccl", device_id=device, timeout=timedelta(seconds=60))
value = torch.tensor([local_rank + 1.0], device=device)
dist.all_reduce(value)
print(f"rank={dist.get_rank()} device={torch.cuda.get_device_name()} sum={value.item()}")
dist.destroy_process_group()
