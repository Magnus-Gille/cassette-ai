---
language:
  - en
tags:
  - chess
  - gpt
  - transformers
  - text-generation
license: mit
datasets:
  - lichess
pipeline_tag: text-generation
library_name: transformers
base_model: gpt2
---

# Chess GPT-4.5M

## Overview

Chess GPT-4.5M is a generative language model trained specifically to generate chess moves and analyze chess games. The model is based on the GPT architecture and was trained with a custom 32-token vocabulary reflecting key chess symbols and notations.

## Model Details

- **Architecture:** GPT-based language model (GPT2LMHeadModel)
- **Parameters:** Approximately 4.5M parameters
- **Layers:** 8 transformer layers
- **Heads:** 4 attention heads per layer
- **Embedding Dimension:** 256
- **Training Sequence Length:** 1024 tokens per chess game
- **Vocabulary:** 32 tokens (custom vocabulary)

## Training Data

The model was trained on tokenized chess game data prepared from the [Lichess dataset](https://huggingface.co/datasets/lichess). The preparation process involved:

- Tokenizing chess games using a custom 32-token vocabulary.
- Creating binary training files (`train.bin` and `val.bin`).
- Saving vocabulary information to `meta.pkl`.

## Training Configuration

The training configuration, found in `config/mac_chess_gpt.py`, includes:

- **Dataset:** lichess_hf_dataset
- **Batch Size:** 2 (optimized for Mac's memory constraints)
- **Block Size:** 1023 (1024 including the positional embedding)
- **Learning Rate:** 3e-4
- **Max Iterations:** 140,000
- **Device:** 'mps' (Mac-specific settings)
- **Other Settings:** No dropout and compile set to False for Mac compatibility

## How to Use

### Generating Chess Moves

After fine-tuning, use the generation script to sample chess moves. Example commands:
bash
Sample from the model without a provided prompt:
python sample.py --out_dir=out-chess-mac
Generate a chess game sequence starting with a custom prompt:
python sample.py --out_dir=out-chess-mac --start=";1.e4"

### Loading the Model in Transformers

Once the model card and converted model files are pushed to the Hugging Face Hub, you can load the model using:

python
from transformers import GPT2LMHeadModel, GPT2Tokenizer
model = GPT2LMHeadModel.from_pretrained("your-hf-username/chess-gpt-4.5M")
tokenizer = GPT2Tokenizer.from_pretrained("your-hf-username/chess-gpt-4.5M")

_Note:_ The tokenizer uses a custom vocabulary provided in `vocab.json`.

## Intended Use

The model is intended for:

- Generating chess move sequences.
- Assisting in automated chess analysis.
- Educational purposes in understanding language model training on specialized domains.

## Limitations

- The model is trained on a relatively small (4.5M parameter) architecture and may not capture extremely complex chess strategies.
- It is specialized on chess move generation and may not generalize to standard language tasks.

## Training Process Summary

1. **Data Preparation:** Tokenized the Lichess chess game dataset using a 32-token vocabulary.
2. **Model Training:** Used custom training configurations specified in `config/mac_chess_gpt.py`.
3. **Model Conversion:** Converted added checkpoint from `out-chess-mac/ckpt.pt` into a Hugging Face compatible format with `convert_to_hf.py`.
4. **Repository Setup:** Pushed the converted model files (including custom tokenizer vocab) to the Hugging Face Hub with Git LFS handling large files.

## Acknowledgements

This model was developed following inspiration from [GPT-2](https://openai.com/blog/better-language-models/) and adapted for the chess domain.

---
