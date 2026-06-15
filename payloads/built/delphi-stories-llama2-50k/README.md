---
language:
- en
license: apache-2.0
datasets:
- delphi-suite/stories
library_name: delphi
---

This is a part of `stories-llama2-*` model family:

name | params | layers | hidden_size | query heads | key & value heads
-|-|-|-|-|-
stories-llama2-50k  | 49,554     | 1 | 6   | 3  | 1
stories-llama2-100k | 99,924     | 1 | 12  | 2  | 1
stories-llama2-250k | 246,820    | 2 | 28  | 2  | 1
stories-llama2-500k | 527,912    | 2 | 56  | 4  | 2
stories-llama2-1m   | 1,019,508  | 4 | 84  | 6  | 3
stories-llama2-2.5m | 2,437,280  | 4 | 160 | 8  | 4
stories-llama2-5m   | 5,136,720  | 5 | 240 | 10 | 5
stories-llama2-10m  | 10,421,340 | 6 | 340 | 10 | 5
stories-llama2-25m  | 24,215,520 | 8 | 480 | 16 | 8
stories-llama2-50m  | 49,387,712 | 8 | 704 | 16 | 8

You can access W&B logs [here](https://wandb.ai/delphi-suite/delphi).

This model was trained using [delphi](https://github.com/delphi-suite/delphi). See `training_config.json` and `run_context.json` for details.





