# Local verification

20 local tests cover actual tiny Qwen/SigLIP/PEFT numerical behavior, data selection,
sampling, loss/gradient parity, frozen/trainable parameters, masking/positions, greedy
generation, normalization, bootstrap, optimizer/dropout/sampler/RNG checkpoint recovery,
atomic generation recovery, and PNG/SVG/PDF/CSV/HTML evidence generation.
The complete test output is in `verification_tests.log`.

Official COCO/VQAv2 source data was downloaded and used to validate exact required quotas.
`DATA_VALIDATION.json` records source-file hashes and the bundled selection checksum.
All 176 grounding evaluation labels were checked programmatically against their category
annotations, and an independent annotated-image gallery was rendered. A small visual
inspection exposed ambiguous broccoli counting and a pluralization error; the documented
counting policy was fixed and selection regenerated before any model predictions.
This is not a claim that every annotation is visually complete or unambiguous.

Default data selection: 18,000 training captions; 1,536 natural training pairs;
96 caption development images; 24/64 grounding dev/test pairs; 32/96 natural dev/test pairs.
Unique image counts: 8,876 train, 208 dev, 320 test; 9,404 total, disjoint across partitions.

Tests ran on CPU with torch 2.6.0, transformers 4.57.1, peft 0.17.1, numpy 2.5.4,
matplotlib 3.11.2, Pillow 13.0.0, Python 3.12.14. No A100 training, full-model accuracy,
GPU throughput, FP16/fused-CUDA stability, or GPU memory claim follows from these tests.
The launcher performs the real-GPU preflight automatically before the official experiment.
