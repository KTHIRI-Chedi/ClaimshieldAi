@echo off
REM ClaimShield AI - installs the scenario version of the workflows into the running n8n container.
REM Run it from the project folder (C:\Users\pc\Documents\ClaimshieldAi) with Docker Desktop running.
setlocal
set C=claimshield_n8n
set W=/data/integration/workflows

echo [1/5] Backing up every workflow currently in n8n to data\integration\backup ...
docker exec %C% n8n export:workflow --all --separate --output=/data/integration/backup/ || goto :error

echo [2/5] Turning off the old 00_ClaimShield_Orchestrator (its form moves into the validation agent) ...
docker exec %C% n8n unpublish:workflow --id=CSorchestrator01

echo [3/5] Adding the "Ollama (local)" credential (the RAG agent runs on gemma2 in Ollama) ...
docker exec %C% n8n import:credentials --input=%W%/ollama_credential.json || goto :error

echo [3/5] Importing the updated workflows (same IDs, so they replace the old versions) ...
for %%F in (01_Document_Ingestion 04_Validation_Fraud_Decision_Agent 03_Visual_Inspection_Agent 03_Invoice_Parser_Agent 05_Incident_Plausibility_Agent 02_Policy_RAG_Agent 04b_Agent_Test_Runner) do (
  docker exec %C% n8n import:workflow --input=%W%/%%F.json || goto :error
)

echo [4/5] Publishing the validation agent and the four agents it calls ...
for %%W in (hyKQcsHn7Jr2K7qH aQlE6lyhtVg2Xo4f 7uwN60tegMMIxTPn VeGTlxAhlxLRtI3N FwCOIOAfJsT7eTvB) do (
  docker exec %C% n8n publish:workflow --id=%%W || goto :error
)

echo [5/5] Restarting n8n so the published versions are used ...
docker restart %C% || goto :error

echo.
echo Done. Wait about 20 seconds, then open http://localhost:5678/form/claimshield
pause
exit /b 0

:error
echo.
echo Something failed above. Nothing else was changed after that step.
pause
exit /b 1
