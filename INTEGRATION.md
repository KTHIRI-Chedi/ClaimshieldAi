# ClaimShield AI : guide d'intégration de l'équipe

Chacun développe sa partie sur **son propre n8n local** (Docker). L'intégration passe par **Git, avec les workflows exportés en `.json`**, jamais par la base n8n.

---

## 1. Principe

| Ce qu'on partage via Git | Ce qu'on NE partage PAS |
|---|---|
| `workflows/*.json` (exports n8n) | `n8n_data/` (base SQLite, comptes, clé de chiffrement) |
| `docker-compose.yml`, `.env.example` | `qdrant_data/` (vecteurs, régénérables) |
| `data/` (police, factures/photos de test) | `.env` (clés API) |
| `scripts/`, docs | |

> ⚠️ Aujourd'hui, `n8n_data/` et `qdrant_data/` sont dans Git. Il faut les retirer, car ils provoquent des conflits à chaque commit et exposent la clé de chiffrement des identifiants (voir §7).

---

## 2. Architecture : un orchestrateur et des sous-workflows

Chaque agent est un **workflow séparé**, avec deux déclencheurs :
- **Manual Trigger** pour tester seul ;
- **When Called by Orchestrator** (*Execute Workflow Trigger*) pour être appelé par le workflow principal.

| Workflow | ID fixe | Responsable |
|---|---|---|
| `00_Main_Orchestrator` (webhook, validation, routage, actions) | `MainOrchestrat00` | Wala Eddine |
| `01_Policy_Ingestion` | `Ettt1j5I9LUcLGeO` | Chedi |
| `02_Policy_RAG_Agent` | `8T1aBC7cg0nWefXt` | Chedi |
| `03_Invoice_Parser_Agent` | `InvParserAgent03` | Fedi / Omar |
| `04_Visual_Inspection_Agent` | `VisualInspect04` | Fedi |
| `05_Fraud_Decision_Agent` | `FraudDecision05` | Omar / Maha |

**Les IDs doivent rester fixes** : l'orchestrateur appelle chaque sous-workflow par son ID. Pour un nouveau workflow, mettez l'ID choisi dans le champ `"id"` du JSON avant le premier import (16 caractères alphanumériques).

---

## 3. Contrat JSON entre agents

Chaque agent **reçoit** et **renvoie** un format fixe. Tant que le contrat est respecté, on peut développer en parallèle. Le décideur et l'orchestrateur testent avec des données figées (*pinned data*) en attendant les vrais agents.

### Entrée commune (envoyée par l'orchestrateur)
```json
{
  "claim_id": "CLM-1001",
  "policy_id": "POL-2026-0042",
  "incident_date": "2026-09-10",
  "incident_location": "Tunis",
  "description": "Collision arrière à un feu rouge",
  "claimed_amount": 1404.2,
  "photo_paths": ["/data/photos/CLM-1001_1.jpg"],
  "invoice_path": "/data/invoices/INV-001.pdf"
}
```

### Sortie : agent Facture (`03`), ✅ implémenté
**Entrée** : `file_path`, `invoice_path` ou `claim.invoice_path` (le premier présent est utilisé).

**Champs lus par l'agent Fraude & Décision** (format validé avec lui) :
```json
{
  "error": false,
  "totals_match": false,
  "arithmetic_issue": "Line \"Right door\": printed 1190.00, expected 890.00",
  "line_items": [
    { "part": "Right door", "type": "part", "quantity": 1, "unit_price": 890, "line_total": 1190 },
    { "part": "Paint ingredients", "type": "other", "quantity": 1, "unit_price": 85, "line_total": 85 },
    { "part": "Labor", "type": "labor", "quantity": 5, "unit_price": 45, "line_total": 225 }
  ]
}
```
- `totals_match` : `true` si les calculs sont justes, `false` en cas d'écart (+15 points), et **`null` si la facture est illisible ou si ce n'est pas une facture** (`status: needs_review`). `null` ne doit pas ajouter de points de fraude : la déclaration part en revue humaine.
- `arithmetic_issue` : texte lisible (plusieurs écarts sont séparés par `; `), ou `null`. Il ne cite que des montants **réellement imprimés** sur la facture : chaque montant extrait par le LLM est vérifié dans le texte, et un montant absent (recalculé ou inventé par le LLM) est écarté et listé dans `ungrounded_amounts`. Si un écart est prouvé par des montants imprimés, `totals_match` vaut `false` ; sinon, un doute donne `null` (revue humaine), jamais une fraude.
- `line_items[].type` : `part` (pièce), `labor` (main-d'œuvre, y compris quand elle est imprimée hors du tableau) ou **`other`** (peinture, consommables, divers). **`other` ne doit pas compter dans la règle « pièce facturée non visible sur les photos »**.
- En cas d'échec (fichier introuvable, OCR, ou les deux LLM), le workflow **ne plante pas** : il renvoie `{ "error": true, "reason": "...", "status": "error", "totals_match": null, "line_items": [] }`.

**Détail complet** (en plus des champs ci-dessus) :
```json
{
  "agent": "invoice_parser",
  "source_file": "/data/invoices/INV-001.pdf",
  "extraction_method": "native_pdf_text | llamaparse_ocr",
  "status": "ok | arithmetic_mismatch | needs_review | error",
  "risk_points": 0,
  "invoice": {
    "is_invoice": true, "invoice_number": "INV-001", "garage_name": "...", "invoice_date": "2026-09-12",
    "vehicle_plate": "...", "claim_ref": "CLM-1001", "currency": "TND", "prices_include_tax": false,
    "line_items": [{ "description": "Front bumper", "category": "part", "quantity": 1, "unit_price": 420,
                     "discount_percent": 10, "vat_rate": 19, "line_total": 378 }],
    "labor": { "hours": 6, "rate": 45, "total": 270 },
    "subtotal": 1180, "discount_total": 0, "net_before_tax": 1180,
    "vat_rate": 19, "vat": 224.2, "tax_lines": [{ "label": "TVA 7%", "rate": 7, "base": 240, "amount": 16.8 }],
    "other_charges": [{ "label": "Timbre fiscal", "amount": 1 }],
    "total": 1404.2
  },
  "claimed_parts": ["Front bumper", "Left headlight"],
  "arithmetic_check": { "ok": true, "issues": [], "unchecked_lines": [], "computed_lines_sum": 1180, "computed_total": 1404.2 },
  "review_reasons": [],
  "ungrounded_amounts": [{ "field": "total", "value": 1999.2 }]
}
```
- `risk_points` vaut 15 uniquement quand `status = arithmetic_mismatch`.
- `claimed_parts` = les `line_items` de type `part` : c'est la liste à comparer avec les pièces visibles sur les photos.

### Sortie : agent Photos (`04`), à implémenter
```json
{
  "agent": "visual_inspection",
  "severity": 3,
  "damaged_parts": ["Front bumper", "Left headlight"],
  "matches_description": true,
  "same_vehicle_all_photos": true,
  "pre_existing_damage": false,
  "photo_date_before_incident": false,
  "duplicate_photo_hashes": [],
  "notes": "..."
}
```

### Sortie : agent Police / RAG (`02`), à adapter
```json
{
  "agent": "policy_rag",
  "covered": true,
  "cited_clauses": ["Clause 4.2", "Section 7"],
  "exclusions_triggered": [],
  "justification": "..."
}
```

### Sortie : agent Fraude & Décision (`05`)
```json
{
  "claim_id": "CLM-1001",
  "risk_score": 25,
  "rule_score": 15,
  "llm_adjustment": 10,
  "warning_signs": [{ "code": "INVOICE_ARITHMETIC", "points": 15, "detail": "..." }],
  "route": "auto_approve | human_review | fraud_investigation",
  "justification": "..."
}
```

> Toute modification d'un contrat se discute dans le groupe **avant** d'être poussée, car elle casse les agents qui en dépendent.

---

## 4. Installation locale (une fois)

```bash
git clone <repo> && cd ClaimshieldAi
cp .env.example .env            # ajouter vos clés (LLAMA_CLOUD_API_KEY, ...)
docker compose up -d
```

1. Ouvrir http://localhost:5678 et créer **votre** compte propriétaire local.
2. Créer les identifiants (*Credentials*) **avec exactement ces noms**, car les workflows importés les retrouvent par leur nom :

| Nom de la credential | Type | Usage |
|---|---|---|
| `NVIDIA_NIM_Free` | OpenAI API (base URL NVIDIA NIM) | LLM et embeddings |
| `Local_Qdrant` | Qdrant API (`http://qdrant:6333`) | base vectorielle |
| `Cohere account` | Cohere API | reranker |
| `OpenAI account` | OpenAI API | vision (GPT-4o) |
| `Groq` *(facultatif)* | OpenAI API, base URL `https://api.groq.com/openai/v1`, clé gratuite sur console.groq.com | LLM de secours de l'agent Facture, chez un autre fournisseur que NVIDIA |

> L'agent Facture se régénère avec `python scripts/build_invoice_workflow.py`. Le script retrouve les credentials **par leur nom** dans votre base n8n locale (les IDs diffèrent d'une machine à l'autre), puis il faut réimporter le JSON (§4.3).

3. Importer tous les workflows :
```bash
docker cp workflows/. claimshield_n8n:/tmp/wf/
docker exec claimshield_n8n n8n import:workflow --separate --input=/tmp/wf/
```
4. Lancer `Document Ingestion & Vector Indexing Pipeline` une fois pour remplir Qdrant.

---

## 5. Workflow Git au quotidien

1. `git pull`, puis réimporter les workflows modifiés par les autres (commande §4.3).
2. Travailler dans **votre** workflow uniquement.
3. Exporter votre workflow :
   ```bash
   docker exec claimshield_n8n n8n export:workflow --id=<ID> --pretty --output=/tmp/out.json
   docker cp claimshield_n8n:/tmp/out.json workflows/<NN_Nom>.json
   ```
4. Commit et push sur une branche (`feat/invoice-agent`, `feat/fraud-decision`, ...), puis une Pull Request.

**Règles :**
- Une personne = un fichier `workflows/*.json`. On ne modifie pas le workflow d'un autre sans le prévenir.
- Avant de commiter, retirer les données figées (*pinned data*) volumineuses et vérifier qu'aucune clé API n'est en clair dans le JSON.
- Les clés API vont **uniquement** dans `.env` ou dans les credentials n8n.

---

## 6. Intégration finale et démo

- Le Team Lead importe tous les `workflows/*.json` sur **une** instance (sa machine ou un serveur partagé).
- Test de bout en bout sur le jeu de test (≥ 20 déclarations étiquetées) : vérifier les routes, le score et le temps de traitement (< 2 min par déclaration).
- Option : un n8n partagé (VPS ou tunnel ngrok) où chacun a un compte, ce qui évite l'export/import, mais le serveur doit rester allumé.

---

## 7. Nettoyage à faire une fois (Team Lead)

```bash
printf 'n8n_data/\nqdrant_data/\n.env\n' >> .gitignore
git rm -r --cached n8n_data qdrant_data
git commit -m "Stop tracking n8n/Qdrant runtime data"
```
Ensuite, **régénérez les clés API** (NVIDIA, Cohere, OpenAI, OpenRouter) : elles ont été commitées dans une base chiffrée, mais avec sa clé de chiffrement.

---

## 8. Points ouverts à décider ensemble

- **Document de police** : le corpus actuel (HDFC Life Group Poorna Suraksha) est une police **vie/santé**, alors que le projet traite des sinistres **auto**. Il faut une vraie police auto pour l'agent RAG.
- **Modèles** : la conception prévoit GPT-4o et `text-embedding-3-small`, mais l'implémentation utilise NVIDIA Nemotron. Il faut choisir et mettre à jour la doc.
- **Latence** : l'agent facture met environ 5 min avec le modèle NVIDIA gratuit, alors que l'objectif est < 2 min par déclaration au total.
- **Airtable** : qui crée la base (tables Policies, Claims, Decisions, Config) et partage le schéma ?
