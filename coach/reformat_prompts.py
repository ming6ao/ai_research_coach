"""One-off content migration: reformat stored task step prompts as Markdown.

The question renderer (``frontend/src/components/Markdown/Markdown.tsx``)
already supports CommonMark, inline/fenced code and KaTeX math; this migration
only adds that presentation structure to prompts that were authored as plain
prose (bullet lists, ordered steps, ```inline code```, ``$...$`` math). No
requirement, number or meaning is changed.

Run with the server stopped. The default is a read-only **dry run**; pass
``--apply`` to write (a DB backup is taken first unless ``--no-backup``):

    python -m coach.reformat_prompts            # dry-run: report what matches
    python -m coach.reformat_prompts --apply    # backup + rewrite in place

``--apply`` rewrites ``tasks.parts_json`` and refreshes task copies embedded in
``active_sessions`` snapshots (any status) so the UI shows the new formatting
immediately. Tasks missing from the target DB, or whose part keys differ from
the mapping, are skipped with a warning (idempotent and safe on a fresh DB).
"""

import argparse
import json
import sqlite3

from coach.db import DB_PATH

# task_id -> {part_key: new markdown prompt}

# task_id -> {part_key: new markdown prompt}
NEW = {
    "seed_training_step": {
        "bp_step": r"""Implement one training step of backpropagation for a 2-layer MLP: a sigmoid hidden layer and a single linear output, minimizing MSE.

Given:
- input `x` and target `y`
- hidden weights `W1`/`b1` and output weights `W2`/`b2`
- a learning rate

Perform:
1. one forward pass
2. compute the output gradient
3. backpropagate through the hidden layer
4. update all weights by gradient descent

Return the updated `(W1, b1, W2, b2)`.""",
        "adam_step": r"""Implement one Adam update step. Given a gradient `g` and the first/second moment accumulators `m` and `v`, apply

$$m \leftarrow \beta_1 m + (1 - \beta_1) g, \qquad v \leftarrow \beta_2 v + (1 - \beta_2) g^2$$

then apply bias correction (divide by $1 - \beta^t$) and return the updated parameter, `m`, and `v` using

$$\text{param}_{new} = \text{param} - lr \cdot \frac{\hat{m}}{\sqrt{\hat{v}} + \epsilon}$$

where $\hat{m}$ and $\hat{v}$ are the bias-corrected moments.""",
        "lr_at_step": r"""Implement a cosine annealing learning-rate schedule with linear warm-up. Given the current step `t`, total steps `T`, warm-up steps `W`, and initial/final learning rates, return the learning rate at step `t`:

- linear ramp up to `lr_init` during warm-up (if `t < W`)
- then cosine decay from `lr_init` down to `lr_final` over the remaining steps""",
    },
    "seed_llm_lifecycle": {
        "bpe_merge": r"""Implement the core of byte-pair encoding:

1. Count adjacent token-pair frequencies across a tokenized corpus (a list of lists of ints).
2. Find the most frequent pair.
3. Return it along with a new corpus where every occurrence of that pair is merged into a single new token id (the current max token id `+ 1`).

Break frequency ties by the lexicographically smaller pair.""",
        "retrieve": r"""Implement minimal lexical retrieval: given a query string and a list of documents, score each document by the number of shared unique terms normalized by the geometric mean of the number of unique terms in the query and the document (a bag-of-words cosine proxy).

Return the indices of the top-`k` documents, ranked highest first.

Tokenize by splitting on whitespace and lowercasing.""",
        "finetune_head": r"""Implement the gradient update for fine-tuning a classifier head while the backbone is frozen.

Given fixed backbone feature vectors (a numpy matrix), one-hot labels, and a trainable head weight matrix `W`, take one gradient descent step on the softmax cross-entropy loss over `logits = features @ W`.

Only `W` is updated (the backbone is frozen). Return the updated `W`.""",
        "quantize_int8": r"""Implement symmetric int8 quantization. Given a list of floats:

- compute $\text{scale} = \max(|x|) / 127$
- quantize each value to $\mathrm{round}(\text{value} / \text{scale})$, clamped to $[-127, 127]$
- return `(quantized, scale)`

Guard against all-zero input by using `scale = 1.0`.""",
        "dequantize_int8": r"""Implement `dequantize_int8(qvalues, scale)` that recovers approximate floats from int8 values by multiplying back by the scale factor.""",
    },
    "seed_deep_architectures": {
        "conv2d_single": r"""Implement a 2D convolution for a single input channel and a single kernel with padding and stride.

Given an input matrix and a kernel matrix, apply zero padding, slide the kernel by stride, and return the output matrix of the correct size:

$$\text{out} = \left\lfloor \frac{\text{in} + 2 \cdot \text{pad} - k}{\text{stride}} \right\rfloor + 1$$

Return a numpy array.""",
        "lstm_cell": r"""Implement one LSTM cell forward pass.

Given input `x`, previous hidden state `h_prev`, previous cell state `c_prev`, and combined weight matrices `W` (input), `U` (recurrent) and bias `b`, compute the four gates (input, forget, cell candidate, output) from `W @ x + U @ h_prev + b`.

- Use sigmoid for the input/forget/output gates and tanh for the candidate.
- Update $c = f \cdot c_{prev} + i \cdot cand$, $h = o \cdot \tanh(c)$.

Return `(h, c)`.""",
    },
    "seed_eval_metrics": {
        "binary_metrics": r"""Implement a confusion matrix and the derived metrics for a binary classifier.

Given lists of true labels and predicted labels (each `0`/`1`), return a dict with:
- the 2x2 confusion matrix `[[TN, FP], [FN, TP]]`
- accuracy, precision, recall, and F1

Guard against division by zero by returning `0.0` for undefined precision/recall/F1.""",
        "train_test_gap": r"""Implement an overfitting detector. Given `x` and `y` lists and a polynomial degree:

1. Fit a least-squares polynomial on the first `(1 - test_frac)` fraction of the data.
2. Compute train MSE on the training portion and test MSE on the held-out portion.

Return `(train_mse, test_mse)`. A large gap between them signals overfitting.""",
    },
    "seed_stats_inference": {
        "bootstrap_ci": r"""Implement a bootstrap confidence interval. Given a list of sample values and a statistic function:

1. Draw `B` bootstrap resamples with replacement.
2. Compute the statistic on each.
3. Return the 2.5th and 97.5th percentiles of the resampled statistics as the 95% CI.

Use a fixed seed so results are reproducible.""",
        "ttest": r"""Implement a one-sample t-test and return the t statistic and a two-sided p-value.

Given a sample and a hypothesized mean `mu0`, compute

$$t = \frac{\bar{x} - \mu_0}{s / \sqrt{n}}$$

using the sample standard deviation with $n - 1$ degrees of freedom. Compute the two-sided p-value with the normal approximation via the error function:

$$p = \mathrm{erfc}\!\left(\frac{|t|}{\sqrt{2}}\right)$$

Do not import scipy. Return `(t, p)`.""",
    },
    "task_a75acb2572": {
        "task_0e61a9a5ed": r"""Implement a fixed-size KV-cache block allocator in C++.

`BlockManager` owns a pool of `num_blocks` physical blocks, each holding `block_size` token slots.

Requirements:
- `allocate(seq_id, num_tokens)` reserves `ceil(num_tokens / block_size)` blocks for a new sequence.
- `append_tokens(seq_id, num_new_tokens)` grows an existing sequence and reserves a new physical block only when the token count crosses a block boundary.
- `free(seq_id)` releases every block owned by the sequence.
- Allocation is **all-or-nothing**: if the pool cannot satisfy a request, reserve nothing and return `false`.""",
        "task_2e22f61c75": r"""Extend the `BlockManager` to support PagedAttention-style logical-to-physical block mappings and shared prefixes.

- Each sequence has a logical block table mapping its logical block index to a physical block id, and every physical block carries a reference count.
- Implement `block_table(seq_id)` to return the sequence's mapping.
- Implement `share_prefix(seq_id, prefix_seq_id, num_blocks)` so `seq_id`'s first `num_blocks` logical blocks point at `prefix_seq_id`'s physical blocks (incrementing each refcount) instead of copying.
- Update `append_tokens` so a newly reserved physical block is mapped into the sequence's table at the correct logical index.""",
        "task_2282264e5f": r"""Add copy-on-write support to the shared-prefix `BlockManager`.

When a sequence writes into a physical block that is shared (reference count greater than 1), it must first copy that physical block to a private block and decrement the original's reference count so that other sequences sharing the prefix are unaffected.

Implement:
- `fork_sequence(seq_id, new_seq_id)` to create a new sequence that shares the parent's block table with incremented reference counts.
- `write_token(seq_id, logical_block, slot, value)` to perform the COW-aware write.
- `free(seq_id)` to decrement reference counts and recycle a physical block only when its count reaches zero.""",
        "task_8794adee62": r"""Make the `BlockManager` safe for multiple inference workers that call `allocate`, `append_tokens`, `free`, `fork_sequence`, `share_prefix`, `block_table`, and `write_token` concurrently.

- Guard all shared state with synchronization primitives from the C++ standard library (for example `std::mutex` or `std::shared_mutex`).
- Ensure a worker can never observe a partially updated block table or reference count.
- Make `free_blocks()` consistent and avoid data races.
- Explain in comments which lock protects which state.""",
    },
    "task_83a9d1077c": {
        "seed_transformer_decode": r"""Implement:
- a numerically stable `softmax` and `log_softmax`
- a single scaled dot-product attention head
- incremental decoding that keeps a key/value cache""",
        "seed_transformer_decode_mask": r"""Extend the attention implementation you wrote for the transformer block so it supports causal masking.

Modify the attention function to accept a `mask` argument: positions where the mask is `False` (or `0`) must be set to a very negative number before the softmax so future tokens cannot attend to themselves.

Implement the mask as an `(n, n)` boolean array where `True` means allowed, and apply it before computing the attention weights.""",
    },
    "seed_dist_training": {
        "ring_allreduce": r"""Implement ring all-reduce on a numpy array across `N` simulated ranks.

1. Do scatter-reduce (`N-1` steps, each rank reduces one chunk from its neighbour).
2. Then all-gather (`N-1` steps), so every rank ends with the elementwise sum of all ranks' inputs.

Use only point-to-point send/recv against a rank list; no global barriers.""",
        "zero_optimizer_step": r"""Implement a ZeRO-1 Adam step.

- Each of `N` ranks stores only its `1/N` slice of the optimizer (`m`, `v`) for a full parameter vector.
- Given full gradients on every rank, each rank updates its shard with the standard Adam rule, then all-gathers the updated shards so every rank holds the full new parameters.

Report the per-rank optimizer memory as a fraction of the naive baseline.""",
        "tensor_parallel_mlp": r"""Implement tensor parallelism for a 2-layer MLP.

- The first linear is column-parallel (each rank holds a slice of the output features and acts on the full input).
- The second is row-parallel (each rank holds a slice of the input features); the partial outputs are summed with the all-reduce from phase 1.

Verify against a single-rank reference within tolerance.""",
        "pipeline_schedule": r"""Implement a 1F1B pipeline schedule for `P` stages and `M` microbatches over a single simulated timeline.

- Return the step at which each microbatch's forward/backward runs.
- Assert the peak number of in-flight microbatches is bounded.
- Compute the bubble fraction $\dfrac{P-1}{M+P-1}$ and compare it to the observed number of idle slots.""",
    },
    "seed_post_training": {
        "bradley_terry_loss": r"""Implement the Bradley-Terry pairwise reward-model loss.

Given rewards for chosen and rejected responses and a `beta` temperature, return the loss

$$-\log \sigma\!\left(\beta (r_{chosen} - r_{rejected})\right)$$

and its gradients with respect to both rewards.""",
        "dpo_loss": r"""Implement the DPO loss for a preference pair.

Given log-probabilities of the chosen and rejected responses under the policy and the frozen reference model, compute

$$\text{logits} = \beta \left[(\text{lp}_{chosen} - \text{ref}_{chosen}) - (\text{lp}_{rejected} - \text{ref}_{rejected})\right]$$

and return $-\log \sigma(\text{logits})$ plus the implicit reward margin.""",
        "ppo_clip_gae": r"""Implement PPO's clipped surrogate objective and generalized advantage estimation.

Given per-step rewards, values, and old log-probs:
1. compute GAE($\lambda$, $\gamma$) advantages/returns
2. then the clipped ratio loss with a ratio clip range

Verify the trust region clips both directions.""",
        "grpo_advantage": r"""Implement GRPO's group-relative advantage:

1. sample `G` completions per prompt
2. score each with the reward model
3. normalize advantages by the group mean and standard deviation
4. add the per-token KL penalty against the reference policy

Return the per-token policy-gradient loss.""",
    },
    "seed_moe": {
        "topk_router": r"""Implement a top-`k` router: given token hidden states and a router weight matrix:

1. compute softmax gate logits
2. select the top-`k` experts per token
3. renormalize the selected gates to sum to 1

Return the expert indices and gate weights.""",
        "capacity_dispatch": r"""Add capacity limiting:

- With capacity factor `C`, each expert accepts at most `ceil(C * tokens_per_expert)` tokens in arrival order; track dropped tokens and count overflow.
- Implement the auxiliary load-balancing loss

$$\mathcal{L}_{aux} = N_{experts} \sum_i \text{fraction\_tokens}_i \cdot \text{mean\_gate}_i$$

Return losses and per-expert token counts.""",
        "expert_parallel_combine": r"""Simulate expert parallelism:

1. assign each expert to one of `E` devices
2. perform all-to-all dispatch of tokens to the devices that own their selected experts
3. run the expert MLPs
4. all-to-all combine the outputs weighted by the gate values

Return the combined output and assert total token count is conserved.""",
        "router_balance_loss": r"""Implement router regularization:

- the router z-loss (mean of $\text{logsumexp}(\text{logits})^2$) for numerical stability
- an auxiliary-loss-free bias correction that nudges per-expert routing biases up/down based on observed load

Return the z-loss and the updated biases.""",
    },
    "seed_flash_attention": {
        "online_softmax": r"""Implement online softmax over a stream of blocks:

- maintain a running max `m` and running denominator `l`
- when a new block arrives, rescale the accumulated output by $\exp(m_{old} - m_{new})$

Return the final normalized output and assert it matches a single-shot softmax within tolerance.""",
        "tiled_attention_forward": r"""Implement a tiled attention forward pass:

1. loop over K/V blocks
2. compute the $QK^T$ block
3. apply online softmax rescaling
4. accumulate the weighted V block
5. divide by the final denominator

Assert that peak memory is $O(\text{block} \cdot d)$ and that output matches dense attention.""",
        "causal_varlen": r"""Add causal masking and variable-length sequence packing.

- Skip K/V blocks that lie entirely above the causal diagonal.
- Mask partial diagonal blocks.
- Process a batch of concatenated variable-length sequences so no token attends across a document boundary.""",
        "attention_backward_recompute": r"""Implement the backward pass without storing the attention matrix:

1. save only the softmax statistics (running max and denominator) in the forward pass
2. recompute the probability block in the backward pass
3. propagate gradients to Q, K, and V

Report the activation memory saved versus the standard implementation.""",
    },
    "seed_spec_continuous": {
        "rejection_sampling_accept": r"""Implement speculative-decoding verification for one drafting step.

Given target and draft next-token distributions and the drafted token:
- accept it with probability $\min\!\left(1, p_{target}/p_{draft}\right)$
- on rejection, sample from the normalized residual $\max(0, p_{target} - p_{draft})$

Return the accepted prefix and verify the output distribution matches sampling from the target.""",
        "tree_verification": r"""Implement tree speculation:

1. build a candidate tree from several draft branches
2. run one target forward pass over the flattened tree with an attention mask that allows each node to attend only to its ancestors
3. select the longest accepted path using the rejection-sampling rule

Verify only one target forward pass is used.""",
        "continuous_batch_scheduler": r"""Implement a continuous-batching scheduler step: given running requests with remaining tokens and a per-step token budget:

1. finish/evict completed requests
2. admit waiting requests while the budget allows
3. report the batch composition, token-budget utilization, and per-step latency model

Prefer to keep decode batches full.""",
        "paged_kv_integration": r"""Integrate the scheduler with a paged KV cache:

- allocate blocks on admission
- append on each decode token (new block only at a boundary)
- free on completion
- preempt the lowest-priority sequence by swapping out its blocks when memory is exhausted

Return free-block counts and assert no leaks.""",
    },
    "seed_long_context": {
        "rope_apply": r"""Implement rotary positional embeddings:

1. for each position, compute the inverse frequencies
2. form sin/cos rotation matrices
3. apply the rotation to `q` and `k`

Verify that the dot product of rotated `q` and `k` depends only on their relative offset.""",
        "yarn_ntk_scaling": r"""Implement context-length extension with YaRN-style scaling:

1. apply the NTK-aware base change
2. blend interpolation frequencies by wavelength
3. add the attention-temperature correction

Show that a model with a 4k window retains per-token perplexity when evaluated at 16k relative to an unscaled baseline.""",
        "sliding_window_sinks": r"""Implement sliding-window attention with attention sinks: each token attends to a small window of recent tokens plus the first few sink tokens and no further.

Return the attention mask and measure the long-range retrieval accuracy versus full attention on a synthetic needle task.""",
        "kv_eviction": r"""Implement attention-score KV eviction (H2O-style):

1. accumulate per-token attention mass over recent steps
2. keep a fixed budget of heavy hitters and evict the rest

Handle re-admission of sink tokens and report cache-size savings and any retrieval loss.""",
    },
    "seed_data_pipeline": {
        "sharded_streaming_reader": r"""Implement a deterministic streaming reader over shard files:

- seed a shuffle of `(shard, offset)` units
- interleave shards with a buffer
- support a resumable cursor so a run can restart exactly where it stopped without a global shuffle barrier""",
        "minhash_dedup": r"""Implement MinHash near-duplicate detection with LSH banding.

1. Compute `k`-shingle MinHash signatures.
2. Bucket into bands/rows and mark any document pair sharing a bucket with Jaccard estimate above a threshold.

Return the set of duplicate document ids and the fraction removed.""",
        "mixture_weights": r"""Implement temperature-based data-mixture sampling. Given source weights and a target token count:

- sample source ids with probabilities proportional to $\text{weight}^{1/T}$
- adjust for observed per-source repetition and track the realized mixture fraction
- include a replay buffer that repeats high-quality sources""",
        "contamination_ngram": r"""Implement evaluation-contamination detection:

1. build an `n`-gram index of training documents
2. flag any benchmark item whose longest shared `n`-gram exceeds a threshold
3. report contaminated-item rate per benchmark

Return the offending spans for inspection.""",
    },
    "seed_agent_eval": {
        "tool_schema_validate": r"""Define tools as JSON schemas and implement argument validation plus repair:

- reject missing/extra/wrong-typed arguments
- coerce numeric strings
- return structured errors the model can act on
- never execute a tool with invalid arguments""",
        "react_loop": r"""Implement a ReAct agent loop:

- alternate thought/action/observation
- enforce max-steps and wall-clock budgets
- retry transient tool errors with backoff
- truncate long observations
- stop on a final answer

Return the trajectory and termination reason.""",
        "pass_at_k_harness": r"""Implement a sandboxed benchmark runner and the unbiased `pass@k` estimator:

1. run `n` samples per task and count the correct ones
2. compute $\text{pass@}k = 1 - \dfrac{\binom{n-c}{k}}{\binom{n}{k}}$
3. aggregate across tasks with per-task breakdowns and flaky-test detection""",
        "best_of_n_elicitation": r"""Implement best-of-`n` elicitation with a verifier:

1. sample `n` candidate solutions per item
2. rank them with a verifier/reward model and select the top one
3. report accuracy with a bootstrap confidence interval over items

Compare `pass@1`, `pass@n`, and verifier-selected accuracy to quantify the elicitation gap.""",
    },
    "remed_290addc695": {
        "solution": r"""Implement a simple REINFORCE policy gradient step calculation function.

Given a 1D PyTorch tensor of log-probabilities for taken actions and a 1D PyTorch tensor of corresponding discounted returns (rewards), compute the policy gradient loss as the mean of negative log-probabilities multiplied by their returns.

Write a function named `compute_policy_loss(log_probs: torch.Tensor, returns: torch.Tensor) -> torch.Tensor` that returns this scalar loss.""",
    },
}


def _matching_tasks(cur) -> dict:
    """Task id -> stored part keys, for every task we actually have a mapping for."""
    stored = {}
    for tid, pj in cur.execute("select id, parts_json from tasks"):
        stored[tid] = {p["key"] for p in json.loads(pj or "[]")}
    matched = {}
    for tid, parts in NEW.items():
        if tid not in stored:
            print(f"skip {tid}: not in this database")
            continue
        if set(parts) != stored[tid]:
            print(
                f"skip {tid}: part keys differ "
                f"(mapped {sorted(parts)} != stored {sorted(stored[tid])})"
            )
            continue
        matched[tid] = parts
    if not matched:
        print("nothing to do")
    return matched


def apply(con):
    cur = con.cursor()
    matched = _matching_tasks(cur)
    cur.execute("BEGIN")
    # 1) tasks table
    changed = 0
    for tid, parts in matched.items():
        pj = cur.execute("select parts_json from tasks where id=?", (tid,)).fetchone()[0]
        parsed = json.loads(pj)
        for part in parsed:
            if part["key"] in parts:
                part["prompt"] = parts[part["key"]]
        cur.execute(
            "update tasks set parts_json=? where id=?",
            (json.dumps(parsed), tid),
        )
        changed += 1
    # 2) refresh task copies inside session snapshots (any status)
    #    fetchall first: executing the UPDATE on the same cursor would reset
    #    the ongoing SELECT and drop every row after the first.
    sessions = 0
    rows = cur.execute("select session_id, session_json from active_sessions").fetchall()
    for sid, sj in rows:
        data = json.loads(sj or "{}")
        sess = data.get("session") or {}
        touched = False
        for task in sess.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            parts = matched.get(task.get("id"))
            if not parts:
                continue
            for part in task.get("parts") or []:
                if part.get("key") in parts:
                    part["prompt"] = parts[part["key"]]
            if task.get("parts"):
                task["prompt"] = task["parts"][0]["prompt"]
            touched = True
        if touched:
            cur.execute(
                "update active_sessions set session_json=? where session_id=?",
                (json.dumps(data), sid),
            )
            sessions += 1
    con.commit()
    print(f"updated {changed} tasks and {sessions} session snapshots")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="write changes (default: dry run)"
    )
    parser.add_argument(
        "--no-backup", action="store_true", help="with --apply, skip the DB backup"
    )
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    try:
        if not args.apply:
            cur = con.cursor()
            matched = _matching_tasks(cur)
            parts = sum(len(p) for p in matched.values())
            print(
                f"dry run: {len(matched)} tasks / {parts} parts would be rewritten "
                "(pass --apply to write)"
            )
            return
        if not args.no_backup:
            from coach.migrate import backup_database

            dest = backup_database()
            if dest:
                print(f"backup written: {dest}")
        apply(con)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
