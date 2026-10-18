"""Writes finetune_qwen_qlora.ipynb (the Colab notebook). Edit the cells here, then run:
    python dev/finetune/build_notebook.py
"""
import json
from pathlib import Path

cells = []


def md(text):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text.strip("\n")})


def code(text):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": text.strip("\n")})


md(r"""
# ClaimShield AI: fine-tuning the reconstruction model (Qwen2.5-3B + QLoRA)

This notebook fine-tunes **Qwen2.5-3B-Instruct** with **QLoRA** (4-bit NF4 base model + LoRA adapters)
to do the *Reconstruct incident* step of the Incident Plausibility agent, then exports it as a GGUF
file that runs on a CPU with Ollama.

**Before you start:** *Runtime → Change runtime type → T4 GPU*. Then run the cells in order
(about 40–60 minutes in total; training itself is about 20–30 minutes).

| Step | What happens |
|---|---|
| 1–2 | Install Unsloth, set the settings |
| 3 | Upload `train.jsonl`, `valid.jsonl`, `test.jsonl` from `dev/finetune/data/` |
| 4–5 | Load Qwen2.5-3B in 4-bit and add LoRA adapters |
| 6 | **Baseline**: evaluate the model *before* training |
| 7–9 | Train (loss only on the answers), plot the loss |
| 10 | **After**: evaluate again, compare |
| 11–12 | Save the LoRA adapter and export GGUF + Ollama Modelfile, download |
""")

md("## 1. Install")
code(r"""
%%capture
# Unsloth: faster QLoRA training on a T4, and GGUF export. It installs matching versions of
# transformers, peft, trl and bitsandbytes.
!pip install unsloth
""")

md(r"""
## 2. Settings
QLoRA = the base model's weights are frozen and stored in **4-bit NF4** (with double quantization);
only small **LoRA** matrices added to the attention and MLP layers are trained (in 16-bit).
""")
code(r"""
MODEL_NAME = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit"  # Qwen2.5-3B-Instruct, pre-quantized to 4-bit NF4
MAX_SEQ_LEN = 1024        # longest example is ~550 tokens

# LoRA
LORA_R = 16               # rank of the update matrices
LORA_ALPHA = 32           # scaling (alpha / r = 2)
LORA_DROPOUT = 0.0        # 0 is fastest with Unsloth; 0.05 is the usual alternative
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",      # attention
                  "gate_proj", "up_proj", "down_proj"]         # MLP

# Training
EPOCHS = 2
LEARNING_RATE = 2e-4
BATCH_SIZE = 4
GRAD_ACCUM = 4            # effective batch = 16
WARMUP_RATIO = 0.05
SEED = 3407

N_EVAL = 80               # test examples used for the before/after comparison (more = slower)
EXPORT_NAME = "claimshield-recon"
""")

md(r"""
## 3. Upload the dataset
Upload the three files from `incident-plausibility/dev/finetune/data/` on your computer
(generated with `node dev/finetune/generate_dataset.js`).
""")
code(r"""
import os, json
needed = ["train.jsonl", "valid.jsonl", "test.jsonl"]
if not all(os.path.exists(f) for f in needed):
    from google.colab import files
    files.upload()   # select train.jsonl, valid.jsonl and test.jsonl
for f in needed:
    assert os.path.exists(f), f"missing {f}"
    print(f, sum(1 for _ in open(f, encoding="utf-8")), "examples")

test_rows = [json.loads(l) for l in open("test.jsonl", encoding="utf-8")]
print(json.dumps(test_rows[0]["messages"], ensure_ascii=False, indent=1)[:1500])
""")

md("## 4. Load Qwen2.5-3B in 4-bit")
code(r"""
import torch
from unsloth import FastLanguageModel, is_bfloat16_supported

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL_NAME,
    max_seq_length=MAX_SEQ_LEN,
    dtype=None,          # auto: float16 on a T4
    load_in_4bit=True,   # QLoRA: 4-bit NF4 base weights
)
print(torch.cuda.get_device_name(0), f"- GPU memory used: {torch.cuda.memory_allocated() / 1e9:.1f} GB")
""")

md(r"""
## 5. Add the LoRA adapters
LoRA's second matrix starts at zero, so right after this cell the model still behaves exactly like
the base model. That is what the baseline evaluation (step 6) measures.
""")
code(r"""
model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_R,
    lora_alpha=LORA_ALPHA,
    lora_dropout=LORA_DROPOUT,
    target_modules=TARGET_MODULES,
    bias="none",
    use_gradient_checkpointing="unsloth",  # saves memory on the T4
    random_state=SEED,
)
model.print_trainable_parameters()
""")

md(r"""
## 6. Evaluation helpers and baseline (before training)
The metrics match the ones in `dev/eval/run_eval.js`: valid JSON, scenario and impact-zone
accuracy, parts overlap (Jaccard), contradiction precision/recall, quote grounding (are the quoted
statements really in the description?) and correct abstention on vague claims.
""")
code(r"""
import re, unicodedata, time

def norm(s):
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    s = re.sub(r"[ً-ْـ]", "", s)          # Arabic diacritics
    return re.sub(r"[^\w]+|_", " ", s).strip()

def supported(quote, text):
    q, t = norm(quote), norm(text)
    if not q: return False
    if q in t: return True
    words = [w for w in q.split() if len(w) > 1]
    if len(words) < 3: return False
    have = set(t.split())
    return sum(w in have for w in words) / len(words) >= 0.8

def parse_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a: return None
    try: return json.loads(text[a:b + 1])
    except Exception: return None

def description_of(row):
    user = row["messages"][1]["content"]
    return user.split("</claimant_description>")[0].replace("<claimant_description>", "").strip()

def generate(messages, max_new_tokens=450):
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
    out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                         pad_token_id=tokenizer.eos_token_id)
    return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

def evaluate(rows, label):
    FastLanguageModel.for_inference(model)
    m = dict(n=0, json_ok=0, scenario_ok=0, zone_ok=0, jaccard=0.0, tp=0, fp=0, fn=0,
             quotes=0, quotes_ok=0, vague=0, abstain_ok=0, seconds=0.0)
    examples = []
    for row in rows:
        gold = json.loads(row["messages"][2]["content"])
        t0 = time.time()
        raw = generate(row["messages"][:2])
        m["seconds"] += time.time() - t0
        pred = parse_json(raw)
        m["n"] += 1
        if len(examples) < 3: examples.append(raw[:400])
        if not isinstance(pred, dict):
            m["fn"] += bool(gold["internal_contradictions"])
            m["vague"] += gold["impact_zone"] == "unknown"
            continue
        m["json_ok"] += 1
        m["scenario_ok"] += pred.get("scenario_type") == gold["scenario_type"]
        m["zone_ok"] += pred.get("impact_zone") == gold["impact_zone"]
        gp, pp = set(gold["expected_parts"]), set(pred.get("expected_parts") or [])
        m["jaccard"] += 1.0 if not gp and not pp else len(gp & pp) / max(1, len(gp | pp))
        desc = description_of(row)
        contras = [c for c in (pred.get("internal_contradictions") or []) if isinstance(c, dict)]
        for c in contras:
            m["quotes"] += 1
            m["quotes_ok"] += supported(c.get("quote_a"), desc) and supported(c.get("quote_b"), desc)
        has_pred = any(supported(c.get("quote_a"), desc) and supported(c.get("quote_b"), desc) for c in contras)
        has_gold = bool(gold["internal_contradictions"])
        m["tp"] += has_pred and has_gold; m["fp"] += has_pred and not has_gold; m["fn"] += has_gold and not has_pred
        if gold["impact_zone"] == "unknown":
            m["vague"] += 1
            m["abstain_ok"] += pred.get("impact_zone") == "unknown" and pred.get("confidence") == "low"
    n = max(1, m["n"])
    result = {
        "model": label,
        "valid JSON": f'{m["json_ok"]}/{m["n"]}',
        "scenario acc": round(m["scenario_ok"] / n, 3),
        "impact-zone acc": round(m["zone_ok"] / n, 3),
        "parts Jaccard": round(m["jaccard"] / n, 3),
        "contradiction precision": round(m["tp"] / max(1, m["tp"] + m["fp"]), 3),
        "contradiction recall": round(m["tp"] / max(1, m["tp"] + m["fn"]), 3),
        "quotes grounded": f'{m["quotes_ok"]}/{m["quotes"]}',
        "abstention": f'{m["abstain_ok"]}/{m["vague"]}',
        "sec / answer (T4)": round(m["seconds"] / n, 1),
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print("\nSample outputs:")
    for e in examples: print("---\n" + e)
    return result

eval_rows = test_rows[:N_EVAL]
before = evaluate(eval_rows, "Qwen2.5-3B base (short prompt)")
""")

md(r"""
## 7. Prepare the training data
Each example is turned into Qwen's chat format. The loss is computed **only on the assistant's
answer** (the JSON), not on the system prompt or the claim text.
""")
code(r"""
from datasets import load_dataset

ds = load_dataset("json", data_files={"train": "train.jsonl", "validation": "valid.jsonl"})
def to_text(ex):
    return {"text": tokenizer.apply_chat_template(ex["messages"], tokenize=False, add_generation_prompt=False)}
ds = ds.map(to_text, remove_columns=ds["train"].column_names)
print(ds)
print(ds["train"][0]["text"][:1200])
""")

md("## 8. Trainer")
code(r"""
import inspect
from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

def build(cls, kwargs):
    # Library versions rename arguments; keep only the names this version accepts.
    renames = {"max_seq_length": "max_length", "eval_strategy": "evaluation_strategy",
               "processing_class": "tokenizer"}
    params = inspect.signature(cls.__init__).parameters
    out = {}
    for k, v in kwargs.items():
        if k in params: out[k] = v
        elif renames.get(k) in params: out[renames[k]] = v
    return cls(**out)

args = build(SFTConfig, dict(
    output_dir="outputs",
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LEN,
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    num_train_epochs=EPOCHS,
    learning_rate=LEARNING_RATE,
    warmup_ratio=WARMUP_RATIO,
    lr_scheduler_type="cosine",
    weight_decay=0.01,
    optim="adamw_8bit",              # 8-bit optimizer states: less GPU memory
    logging_steps=10,
    eval_strategy="steps",
    eval_steps=40,
    save_strategy="no",
    fp16=not is_bfloat16_supported(),
    bf16=is_bfloat16_supported(),
    seed=SEED,
    report_to="none",
))
trainer = build(SFTTrainer, dict(
    model=model,
    processing_class=tokenizer,
    train_dataset=ds["train"],
    eval_dataset=ds["validation"],
    args=args,
))
# Mask everything except the assistant's answer.
trainer = train_on_responses_only(trainer,
                                  instruction_part="<|im_start|>user\n",
                                  response_part="<|im_start|>assistant\n")

# Check the masking: only the JSON answer should be printed here.
labels = [t for t in trainer.train_dataset[0]["labels"] if t != -100]
print(tokenizer.decode(labels)[:400])
""")

md("## 9. Train")
code(r"""
FastLanguageModel.for_training(model)
stats = trainer.train()
print(stats)

import matplotlib.pyplot as plt
hist = trainer.state.log_history
tr = [(h["step"], h["loss"]) for h in hist if "loss" in h]
ev = [(h["step"], h["eval_loss"]) for h in hist if "eval_loss" in h]
plt.figure(figsize=(7, 4))
plt.plot(*zip(*tr), label="train loss")
if ev: plt.plot(*zip(*ev), "o-", label="validation loss")
plt.xlabel("step"); plt.ylabel("loss"); plt.title("QLoRA fine-tuning, Qwen2.5-3B"); plt.legend(); plt.grid(alpha=.3)
plt.savefig("loss_curve.png", dpi=150, bbox_inches="tight"); plt.show()
""")

md("## 10. Evaluate after training and compare")
code(r"""
after = evaluate(eval_rows, "Qwen2.5-3B + QLoRA (fine-tuned)")

import pandas as pd
table = pd.DataFrame([before, after]).set_index("model").T
display(table)
table.to_csv("before_after.csv")
""")

md(r"""
## 11. Save the LoRA adapter
The adapter is only the trained LoRA weights (tens of MB). Keep it for the report and to re-export later.
""")
code(r"""
model.save_pretrained(f"{EXPORT_NAME}-lora")
tokenizer.save_pretrained(f"{EXPORT_NAME}-lora")
!zip -qr {EXPORT_NAME}-lora.zip {EXPORT_NAME}-lora
print("saved", f"{EXPORT_NAME}-lora.zip")
""")

md(r"""
## 12. Export to GGUF for Ollama (CPU)
Merges the adapter into the base model and quantizes to **Q4_K_M** (~2 GB, runs on a laptop CPU).
The first run builds llama.cpp, which takes several minutes.
""")
code(r"""
import glob, shutil
model.save_pretrained_gguf(EXPORT_NAME, tokenizer, quantization_method="q4_k_m")
ggufs = sorted(glob.glob(f"{EXPORT_NAME}*/*.gguf") + glob.glob(f"{EXPORT_NAME}*.gguf") + glob.glob("*.gguf"))
ggufs = [g for g in ggufs if "q4_k_m" in g.lower()] or ggufs
print(ggufs)
gguf = ggufs[0]
shutil.copy(gguf, f"{EXPORT_NAME}-Q4_K_M.gguf")

# Ollama Modelfile: Qwen's ChatML format, stop tokens, and a context large enough for the prompt.
Q3 = '"' * 3
modelfile = "\n".join([
    f"FROM ./{EXPORT_NAME}-Q4_K_M.gguf",
    "TEMPLATE " + Q3 + "{{- range .Messages }}<|im_start|>{{ .Role }}",
    "{{ .Content }}<|im_end|>",
    "{{ end }}<|im_start|>assistant",
    Q3,
    'PARAMETER stop "<|im_end|>"',
    'PARAMETER stop "<|endoftext|>"',
    "PARAMETER num_ctx 2048",
    "PARAMETER temperature 0.7",
    "",
])
open("Modelfile", "w").write(modelfile)
print(modelfile)
""")

md("## 13. Download the results")
code(r"""
from google.colab import files
for f in [f"{EXPORT_NAME}-Q4_K_M.gguf", "Modelfile", f"{EXPORT_NAME}-lora.zip", "before_after.csv", "loss_curve.png"]:
    if os.path.exists(f):
        print("downloading", f)
        files.download(f)
# Large files can be slow to download from the browser. Alternative: copy them to Google Drive:
# from google.colab import drive; drive.mount('/content/drive'); shutil.copy(f"{EXPORT_NAME}-Q4_K_M.gguf", "/content/drive/MyDrive/")
""")

md(r"""
## Next: run it on your computer
In the folder where you saved `claimshield-recon-Q4_K_M.gguf` and `Modelfile`:

```
ollama create claimshield-recon -f Modelfile
ollama run claimshield-recon "hello"
```

Then follow `dev/finetune/README.md` (step 5) to connect it to the n8n workflow.
""")

nb = {
    "nbformat": 4, "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {"name": "python3", "display_name": "Python 3"},
        "language_info": {"name": "python"},
        "accelerator": "GPU",
        "colab": {"provenance": [], "gpuType": "T4"},
    },
    "cells": [
        {**c, "source": [line + "\n" for line in c["source"].split("\n")[:-1]] + [c["source"].split("\n")[-1]]}
        for c in cells
    ],
}
out = Path(__file__).parent / "finetune_qwen_qlora.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", out, f"({len(cells)} cells)")
