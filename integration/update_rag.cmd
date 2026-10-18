@echo off
REM ClaimShield AI - updates only the RAG workflow (new system prompt, retry keeps the claim, longer answers).
REM Run it from the project folder (C:\Users\pc\Documents\ClaimshieldAi) with Docker Desktop running.
setlocal
set C=claimshield_n8n
echo [1/3] Importing the updated RAG workflow ...
docker exec %C% n8n import:workflow --input=/data/integration/workflows/02_Policy_RAG_Agent.json || goto :error
echo [2/3] Publishing it ...
docker exec %C% n8n publish:workflow --id=FwCOIOAfJsT7eTvB || goto :error
echo [3/3] Restarting n8n ...
docker restart %C% || goto :error
echo.
echo Done.
pause
exit /b 0
:error
echo Something failed above.
pause
exit /b 1
