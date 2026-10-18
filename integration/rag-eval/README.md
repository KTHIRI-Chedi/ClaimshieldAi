# Retrieval evaluation: three chunking strategies

Compares how well three chunkings of the Liberty Private Car Package policy PDF retrieve the clause that answers a claim question.

- `queries.json`: 18 questions in the client's words, each with the exact clause phrase that answers it (`gold`).
- `eval.py`: builds the chunks (A: recursive 500/50 characters, as ingested today; B: recursive 1000/200; C: one chunk per clause heading, max 1,200 characters), retrieves with BM25, and counts a hit when the gold phrase is in the first 1,200 characters of a retrieved chunk (the part the RAG prompt shows).
- `results.json`: the output.

| Strategy | Chunks | Avg chars | Hit in top 4 | Hit in top 20 | MRR |
|---|---|---|---|---|---|
| A. Recursive 500/50 (built) | 411 | 392 | 6/18 | 10/18 | 0.324 |
| B. Recursive 1000/200 | 241 | 756 | 7/18 | 14/18 | 0.341 |
| C. Clause headings, max 1200 | 230 | 744 | 11/18 | 12/18 | 0.392 |

BM25 is a stand-in for the production retriever (Nemotron embeddings + Cohere rerank), which could not be called from the evaluation environment. It compares the strategies fairly but does not measure the live system.

Rerun: `pdftotext "Policy Wordings for Private car Package policy V_16072024.pdf" raw.txt`, then `pip install langchain-text-splitters rank_bm25` and `python eval.py` in this folder.
