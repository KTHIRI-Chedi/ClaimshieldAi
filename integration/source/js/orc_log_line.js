// One JSON line per claim in data/claimshield/decisions_log.jsonl (audit trail: every agent result is kept).
const { page, slack, settings, ...record } = $input.first().json;
const line = JSON.stringify({ type: 'decision', ...record }) + '\n';
return [{ json: { claim_id: record.claim_id, route: record.route },
          binary: { log: { data: Buffer.from(line, 'utf8').toString('base64'), mimeType: 'application/x-ndjson', fileName: 'decisions_log.jsonl' } } }];
