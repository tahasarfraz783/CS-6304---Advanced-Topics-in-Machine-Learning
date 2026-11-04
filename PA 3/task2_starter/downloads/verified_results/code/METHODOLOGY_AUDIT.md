# Requirement audit

Source: `inputs/task2_requirements.txt`, copied unchanged from the supplied attachment.

| Requirement | Implementation / evidence |
|---|---|
| Original Qwen3-0.6B, thinking disabled | `VLM` loads original HF ID; template `enable_thinking=False`; model commit frozen on first model load |
| SigLIP frozen, 196×768, final LN once | Vision model eval/frozen; use returned last_hidden_state; shape/finiteness assertions; saved processor/config |
| FP16 deterministic feature cache; unload encoder | Atomic NumPy shards, deterministic processor, then delete/GC/empty cache before Qwen |
| Two-layer connector, fixed training-only magnitude rule | FP32 MLP; recorded training-caption RMS calibration |
| User-message insertion and response-only labels | Chat prefix split at sentinel inside user content; matching left padding, attention, rebuilt positions |
| Connector gradients through frozen LM | Actual tiny-Qwen loss/gradient parity test and real-GPU interface assertion |
| Caption 6000×3, dev96×1 | Seeded caption image/annotation selection in manifest; two shuffled Stage 1 passes |
| Programmatic presence/counting pairs | Annotation pools; complete-pair draws; counts1–4; crowd exclusion for counting |
| Natural quotas, ≥8/10, differing normalized consensus | Official pair lists, all-ten-answer retention, original consensus target strings |
| Dev/test image-disjoint across all suites | Selection shares one used-image exclusion set; split audit; train2014 vs val2014 |
| No forced stage mixture quotas | Seeded random component choice per pair draw; sampled counts logged |
| Same model through 2250/1500/750 updates | One VLM object; LoRA enabled at Stage 2; new stage optimizers/schedules |
| Batch8 accumulation2; FP16 AMP/FP32 trainables/states | Loop divides microbatch means by2; fused AdamW, dynamic scaler; unscale before clipping |
| Per-example loss incl termination | Select only supervised shifted labels; token mean per example then batch mean |
| Caps80/64/16 | Question content cap before chat wrapping; response cap before end-of-turn token |
| LoRA r16/a32/drop.05/qkvo/no biases | PEFT config; tests assert backbone stays frozen and adapters/connector receive gradients |
| Warmup5%, cosine to10% | Stage-local analytic scheduler state stored in checkpoint; rounded warmup update count |
| Required250-update and stage exports | Atomic trainable+optimizer/scaler/sampler/RNG checkpoint; original backbone commit reloaded; stage connector/adapters/tokenizer |
| Before/every500/endpoints dev | Explicit global and stage-end triggers; cached completed dev files |
| Correct/swap/none dev NLL | Original refs; termination excluded for answer NLL; per-example files retained |
| Four final conditions; fixed mismatch; no-image rebuilding | Fixed mappings before generation; excludes original pair images; unchanged refs/text |
| Greedy16 batch8 | Batched HF generation with cache; thinking-disabled prefix; end-of-turn EOS |
| EM vs local soft consensus; question-type breakdown | Official normalization mapping; exact formula tested at3 matches→.9; suite/type tables |
| Pair/identical/empty/NLL/time diagnostics | Per-example raw records and final pair-group aggregation; empty outputs retained |
| 4000 pair bootstrap, matched differences | Shared pair-index resamples across conditions in each suite/type |
| Swaps follow partner vs unsupported changes | Partner canonical match and neither-original-nor-partner rates; raw outputs/gallery |
| Required plots, tables, qualitative evidence | PNG/SVG/PDF curves/bar charts; CSV tables; fixed ID-selection aligned image gallery |
| Resource evidence including caching | Stage params/speed/memory; cache timing; generation timing/memory; sampled GPU utilization; run-session wall time |
| Annotation inspection independent of outputs | All dev/test grounding annotated-box review gallery and editable review template before predictions |
| Optional49-token experiment | Separate config/output; exact spatial2×2 mean reduction before fresh connector/adapters; not automatic |

## Verification boundary

The local suite checks real tiny Qwen forwards, batched cached generation, nonreentrant
checkpointing with real PEFT adapters, selected-vocabulary loss/gradient parity, optimizer
and RNG recovery, final generation cache recovery, normalization, pair sampling,
isolation rejection, paired bootstrap, and all three plot formats. It uses CPU tensors.

The A100 preflight tests the real model, FP16 AMP, fused CUDA optimizer, training
microbatches, cached generation, and likelihood batch choices. It runs automatically
before the official run. Full-scale learning results and A100 speed/memory remain
unmeasured until the user runs the cloud launcher. The scripts do not fabricate evidence.

The human report still requires independent label inspection, interpretation of actual
learning curves and controls, and discussion of annotation/metric/generalization limits.
The generated tables and gallery support that analysis; they cannot substitute for it.
