# Understand the code in seven small passes

You do not need to understand all the infrastructure before understanding the experiment.
Read the files in this order, then follow one example through them.

## 1. `config.json`: what stays the same?

Find `examples`, `microbatch`, and `accumulation`. Calculate:

```text
effective batch = 2 * 16 = 32 examples
updates in an epoch = 40000 / 32 = 1250
```

Every method sees the same saved examples in the same order. Each independently loads the
same starting weights. Methods differ in what they train and how updates are restricted.

## 2. `data.py`: what does one example become?

Start with `encode_example()` and `collate()`.

```text
Question: [the student's math question]
Answer:   [the supplied worked solution]

input_ids = [user/chat prefix] [assistant response] [end-of-turn]
labels    = [-100, -100, ...]  [same response IDs]  [end-of-turn ID]
```

`-100` is the loss function's ignore marker. The model can read question tokens, but it is
not penalized for failing to predict them. Padding also gets ignored.

The causal language-model loss shifts predictions internally: the logits at position t
predict the label at position t+1. This is why training counts `labels[:, 1:]`.

Try explaining aloud: why would training on padding or on the question itself change the
meaning of the objective?

Then read `prepare()`. It filters source rows, saves source IDs, and creates a frozen tokenized
file. It does not shuffle or truncate retained answers. All five runs read that same file.

## 3. `model.py`: what is the difference between the five models?

The architecture stays Qwen. For Full FT, original parameters are trainable. L2-SP uses those
same trainable parameters plus a penalty in the training loop.

For LoRA, find `LowRankLinear.forward()`:

```python
correction = B(A(dropout(x)))
output = original_linear(x) + scale * correction
```

This is the notes' `W0 x + (alpha/r) BA x`. The actual code uses `linear()` so PyTorch handles
the matrix dimensions and transposes. Only A and B get gradients; the original matrix is frozen.

Follow the shapes for a 1024-input, 1024-output layer and rank 16:

```text
x:       (..., 1024)
A:       (16, 1024)
Ax:      (..., 16)
B:       (1024, 16)
B(Ax):   (..., 1024)
```

Now find `factors()`. Ordinary LoRA returns A and B. OPLoRA first subtracts their components
along protected input/output directions. The rest of the training code can stay the same.

Find the random-A/zero-B initialization. Explain why the initial correction is zero even
though A is random. Rank 16 and OPLoRA start with the same unprojected factors under the seed.

## 4. `training.py`: understand ONE optimizer update

The large loop repeats this sequence:

1. Take the next 32 saved examples, without shuffling.
2. Count valid response tokens across all 32.
3. Split into 16 microbatches of two examples.
4. For each microbatch, run the model, compute response loss, and backpropagate.
5. For L2-SP only, backpropagate the starting-point penalty once.
6. Unscale gradients, clip their global norm, and attempt an AdamW update.
7. Update the learning-rate schedule if the AMP update succeeded.
8. Save the measured losses, learning rate, time, and any skipped update.

The optimizer is updated once per 32 examples, not once per microbatch.

### Why the loss weighting looks unusual

Suppose microbatch A has 100 response tokens and microbatch B has 900.
Their mean losses are 2 and 4. Averaging their means gives 3, but the token mean is:

```text
(100*2 + 900*4) / 1000 = 3.8
```

The code multiplies each microbatch's mean by its fraction of valid tokens. That implements
the assignment's normalization across the entire effective batch. Do not additionally
divide this weighted loss by 16.

### What L2-SP adds

`proximity()` computes `0.5 * sum((parameter - starting_parameter)**2)`.
It sums over parameters; it does NOT divide by parameter count. The fixed reference is
the starting model, while AdamW's separate weight decay acts toward zero.

### What a recovery checkpoint saves

Weights alone are not enough for a faithful continuation. The checkpoint also includes
Adam moments, LR scheduler, gradient scaler, random-number states, and the completed update.
Because the dataset order is fixed, the next data offset is `completed_update * 32`.

## 5. `evaluation.py`: what do the trained weights actually do?

Training loss asks whether the model predicts the supplied MetaMath responses. Benchmarks
ask whether that learning transfers and whether other abilities changed.

The harness handles task prompts, candidate likelihoods, and answer extraction. The wrapper
only adds generation-length/truncation records. Read `evaluate()` before the wrapper class.

Adapters are exported and merged into fresh backbone copies. `evaluation_model()` compares
unmerged versus merged logits before using merged weights for benchmarks. For OPLoRA, the
exported factors already include the projections.

There are seven conditions: baseline, Full FT midpoint, and five finals. Qualitative prompts
are repeated unchanged for each condition; their responses are saved for YOUR annotations.

## 6. `diagnostics.py`: connect weights to internal computations

Read `measure()`:

- `eta`: update norm / original matrix norm. How BIG is the update?
- `rho`: protected output-subspace update energy / total update energy. WHERE does it act?
- `R`: correction output norm / original output norm for the same cached input. WHEN does it act?

The same cached base activations are used for every method. An unrelated prompt can still
activate a math-trained correction. A large local correction does not prove the final answer
will be harmful; later network computation matters too.

## 7. `run.py` and `plots.py`: orchestration, not new learning rules

Finally read `main()` in the launcher. Each worker is a normal Python subprocess. Exiting
training before evaluation frees its GPU model and optimizer states. The parent just
coordinates stages, streams logs, refreshes evidence, and checks completion.

`plots.py` reads saved CSV/JSON files and writes SVGs. It never reruns training and never
invents missing benchmark values. You can refresh figures later with `--mode plots`.

After reading, you should be able to explain:

1. What is frozen and trainable in each method?
2. Why do all methods start independently?
3. Why can LoRA change non-math behavior even with a frozen backbone?
4. Why is low SFT loss insufficient evidence of a good adaptation/retention trade-off?
5. Which results are automatic measurements, and which require your own interpretation?
