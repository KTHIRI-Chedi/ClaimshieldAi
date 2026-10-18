# Automated Testing Guide for Full RAG Workflow

## Overview

This guide explains how to use the automated testing script to test your complete RAG workflow including:
- Chat Trigger
- RAG Agent (with Qdrant retrieval)
- LLM generation
- LLM-as-a-Judge evaluation
- Final response

## Prerequisites

### 1. Enable n8n API Access

**Option A: Use Basic Auth (Recommended for local testing)**

The script uses n8n's API with basic authentication. Your docker-compose.yml already has this configured:
- Username: `admin`
- Password: `claimshield_pass`

**Option B: Generate API Key**

If you prefer using an API key:

1. Open n8n: http://localhost:5678
2. Go to Settings → API
3. Create a new API key
4. Add the key to the script:
   ```python
   api_key = "your-api-key-here"
   ```

### 2. Get Your Workflow ID

The script needs the workflow ID to execute it directly. From our earlier analysis:
- **RAG Agent & LLM-as-a-Judge Pipeline ID:** `tzhK9oclX70xj6aK`

### 3. Activate the Workflow

1. Open n8n: http://localhost:5678
2. Navigate to "RAG Agent & LLM-as-a-Judge Pipeline"
3. Click the toggle to activate it

## Running the Automated Tests

### Quick Start

```bash
# Install required packages
pip install requests

# Run the test script
python test_full_rag_workflow.py
```

### Configuration

Edit the script to configure:

```python
# Line ~490 in test_full_rag_workflow.py
n8n_url = "http://localhost:5678"
workflow_id = "tzhK9oclX70xj6aK"  # Your workflow ID
api_key = None  # Add your API key if using one
```

### What the Script Does

For each of the 50 test cases:

1. **Submits query** to the n8n workflow via API
2. **Captures response** from the agent
3. **Extracts LLM-as-a-Judge evaluation** (score, pass/fail, reasoning)
4. **Evaluates response quality:**
   - Retrieval Quality (1-5)
   - Groundedness (1-5)
   - Precision (1-5)
5. **Calculates overall score** and pass/fail
6. **Records execution time**
7. **Saves results** to JSON and CSV

### Expected Output

```
ClaimShield AI - Full RAG Workflow Automated Tester
======================================================================

======================================================================
Category: Basic Policy Information
Description: Tests retrieval of fundamental policy details
======================================================================

----------------------------------------------------------------------
Test TC001: What is the free-look period for policy cancellation?
Difficulty: easy
Type: fact_retrieval
Expected: 15 days (or 30 days in case the Master Policy has been issued...

Execution Time: 2.34s
Agent Response: The free-look period is 15 days (or 30 days if issued...
Judge Score: 5
Judge Pass: True
Judge Reasoning: Response is accurate and cites the correct clause

Evaluation Scores:
  Retrieval Quality: 5/5
  Groundedness: 5/5
  Precision: 5/5
  Overall Score: 5.0/5
  Passed: True
✓ PASSED
```

### Results Files

The script generates two result files:

1. **JSON Format:** `rag_workflow_test_results_YYYYMMDD_HHMMSS.json`
   - Complete data with all fields
   - Useful for programmatic analysis

2. **CSV Format:** `rag_workflow_test_results_YYYYMMDD_HHMMSS.csv`
   - Spreadsheet-ready
   - Easy to import into Excel/Google Sheets

## Troubleshooting

### Error: "Failed to create chat" or "Execution failed"

**Solution 1: Check n8n is running**
```bash
docker ps
# Look for claimshield_n8n container
```

**Solution 2: Verify workflow is active**
- Open n8n: http://localhost:5678
- Check the workflow toggle is ON

**Solution 3: Check API access**
- n8n API may require authentication
- Try adding basic auth credentials to the script:

```python
# Modify the execute_workflow_by_id method
headers = {
    "Content-Type": "application/json",
    "Authorization": "Basic " + base64.b64encode(b"admin:claimshield_pass").decode()
}
```

### Error: "Workflow not found"

**Solution:** Verify the workflow ID is correct
- Open n8n
- Check the workflow URL for the ID
- Update the script with the correct ID

### Error: "No output in response"

**Solution:** The workflow may not be returning data in the expected format
- Manually test the workflow first
- Check the output structure
- Modify the `evaluate_response` method to match your workflow's output

## Alternative: Manual Testing via Script

If API access doesn't work, you can use the script as a test runner and manually input results:

```python
# Modify to skip API calls and record manual results
def manual_test_mode(self):
    for test_case in test_cases:
        print(f"Query: {test_case['query']}")
        print(f"Expected: {test_case['expected_answer']}")

        # Run manually in n8n chat
        agent_response = input("Enter agent response: ")
        judge_score = int(input("Enter judge score (1-5): "))
        judge_pass = input("Pass? (y/n): ").lower() == 'y'

        # Evaluate and record
        result = self.evaluate_response(test_case, agent_response, judge_score, judge_pass)
        self.test_results.append(result)
```

## Interpreting Results

### Score Breakdown

- **Retrieval Quality (1-5):** How well the expected clauses were found
- **Groundedness (1-5):** How well the response is supported by retrieved context
- **Precision (1-5):** Accuracy of numbers and specific details
- **LLM-as-a-Judge (1-5):** The judge's quality score from your workflow
- **Overall Score:** Average of the three evaluation metrics

### Pass Criteria

- **Overall Score ≥ 3.0** AND
- **LLM-as-a-Judge Pass = True**

### Common Failure Patterns

1. **Low Retrieval Quality:** Expected clauses not in response
   - Fix: Improve chunking or metadata in Qdrant

2. **Low Groundedness:** Response has hallucinated information
   - Fix: Strengthen agent prompt to stick to retrieved context

3. **Low Precision:** Wrong numbers or specific details
   - Fix: Improve prompt to extract exact figures

4. **Judge Fail:** LLM-as-a-Judge rejected the response
   - Fix: Improve response quality or adjust judge thresholds

## Running a Subset of Tests

To test only specific categories, modify the script:

```python
# In run_test_suite method, add filtering
for category in dataset['test_categories']:
    # Only test specific categories
    if category['category'] not in ['Basic Policy Information', 'Exclusions']:
        continue

    for test_case in category['test_cases']:
        # ... rest of the code
```

## Continuous Integration

You can integrate this into CI/CD:

```yaml
# Example GitHub Actions workflow
- name: Test RAG Workflow
  run: |
    pip install requests
    python test_full_rag_workflow.py

- name: Upload Results
  uses: actions/upload-artifact@v2
  with:
    name: test-results
    path: rag_workflow_test_results_*.json
```

## Next Steps

1. **Run initial test suite** to establish baseline
2. **Analyze failure patterns** to identify weak areas
3. **Optimize workflow** based on findings
4. **Re-test** to measure improvements
5. **Set up scheduled testing** for regression detection

## Support

For issues with:
- **n8n API:** https://docs.n8n.io/api/
- **Qdrant:** http://localhost:6333/dashboard
- **Test dataset:** See test_dataset.json and MANUAL_TESTING_GUIDE.md
