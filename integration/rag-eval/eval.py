import re, json, unicodedata, statistics
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"\s+", " ", s).strip()

text = open("raw.txt", encoding="utf-8").read()

# A: what the ingestion workflow does today
def recursive(size, overlap):
    return RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap).split_text(text)

# B: structure-aware, one chunk per clause, long clauses sub-split with the clause title repeated
HEAD = re.compile(r"^(Section (I|II|III)\b.*|General Exceptions.*|Deductible\s*$|Conditions:?\s*$|Exclusions:?\s*$|Special (Conditions|Exclusions).*|Scope of Cover.*|M?IMT\s*\.?\s*\d+.*|AD\s*-\s*?\d+\..*|OPTIONAL ADD ON COVER.*|Rate of depreciation for painting.*|Avoidance of Certain Terms.*|Sum Insured.*|Application of limits.*)$", re.I)
def structure(maxlen=1200, overlap=150):
    lines = text.split("\n"); secs = []; title = "Preamble"; buf = []
    for ln in lines:
        if HEAD.match(ln.strip()):
            if buf: secs.append((title, "\n".join(buf)))
            title, buf = ln.strip(), [ln]
        else:
            buf.append(ln)
    if buf: secs.append((title, "\n".join(buf)))
    sub = RecursiveCharacterTextSplitter(chunk_size=maxlen - 80, chunk_overlap=overlap)
    out = []
    for t, body in secs:
        if len(body.strip()) < 40: continue
        parts = sub.split_text(body) if len(body) > maxlen else [body]
        for i, p in enumerate(parts):
            out.append(p if i == 0 else f"[{t}]\n{p}")
    return out

Q = json.load(open("queries.json"))
STOP = set("the a an of to in is and or for on my was it at by with be are i me what how does do if this that from".split())
def tok(s): return [w for w in re.findall(r"[a-z0-9]+", norm(s)) if w not in STOP]

def evaluate(name, chunks):
    bm = BM25Okapi([tok(c) for c in chunks])
    hit4 = rec20 = mrr = 0; rows = []
    for q in Q:
        sc = bm.get_scores(tok(q["q"]))
        order = sorted(range(len(chunks)), key=lambda i: -sc[i])[:20]
        g = norm(q["gold"]); rank = None
        for r, i in enumerate(order, 1):
            # what the RAG prompt actually shows: the first 1200 characters of each clause
            if g in norm(chunks[i][:1200]): rank = r; break
        hit4 += rank is not None and rank <= 4; rec20 += rank is not None
        mrr += 1 / rank if rank else 0; rows.append(rank)
    n = len(Q); L = [len(c) for c in chunks]
    return dict(strategy=name, chunks=len(chunks), avg_chars=round(statistics.mean(L)), hit_at_4=f"{hit4}/{n}",
                hit4_pct=round(100*hit4/n), recall_at_20=f"{rec20}/{n}", mrr=round(mrr/n, 3), ranks=rows)

res = [evaluate("A. Recursive 500/50 chars (built)", recursive(500, 50)),
       evaluate("B. Recursive 1000/200 chars", recursive(1000, 200)),
       evaluate("C. Structure-aware (clause headings, max 1200)", structure())]
for r in res: print(json.dumps(r))
json.dump(res, open("results.json", "w"), indent=1)
