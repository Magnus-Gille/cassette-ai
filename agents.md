# Project: Cassette LLM viability sprint

## Stack
- Python 3.11+, numpy, scipy, matplotlib, transformers, torch, reedsolo, soundfile
- Models cached in ./hf_cache (set HF_HOME)
- Random seeds always set and logged

## Conventions
- All experimental code in src/, run scripts in scripts/, outputs in RESULTS/
- Plots saved as PNG to RESULTS/plots/, raw data as CSV/JSON to RESULTS/data/
- Each script writes a one-paragraph summary to REPORT.md on completion
- Prefer scipy.signal and reedsolo over hand-rolled DSP/ECC where they exist

## Don't
- Don't attempt physical hardware integration
- Don't refactor working code for elegance
- Don't redownload HuggingFace models if already cached
- Don't add CI, packaging, or production polish