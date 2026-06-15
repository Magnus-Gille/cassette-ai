---
license: mit
tags:
- pytorch
- diffusers
- unconditional-image-generation
- diffusion-models-class
datasets:
- mnist
library_name: diffusers
pipeline_tag: unconditional-image-generation
thumbnail: https://upload.wikimedia.org/wikipedia/commons/f/f7/MnistExamplesModified.png
---

# Unconditional MNIST DDPM

![](https://upload.wikimedia.org/wikipedia/commons/f/f7/MnistExamplesModified.png)

## Description

This model is a very lightweight UNet2D trained on the MNIST dataset. \
This model is unconditional, meaning that you cannot pick which number you'd like to generate. \
This model was trained in ~40min on an L4 GPU Google Colab instance. You can see the training logs in the [Training metrics](https://huggingface.co/1aurent/ddpm-mnist/tensorboard) tab.

A conditional model is available at [1aurent/ddpm-mnist-conditional](https://huggingface.co/1aurent/ddpm-mnist-conditional), though it is pretty buggy.

## Usage

```python
from diffusers import DDPMPipeline

pipeline = DDPMPipeline.from_pretrained('1aurent/ddpm-mnist')
image = pipeline().images[0]
image
```