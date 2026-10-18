// The adjuster's answer on Slack is added to the audit log.
const r = $('Decision Record').first().json;
const approved = $json.data?.approved;
const answer = approved === true ? 'approved' : approved === false ? 'rejected' : 'no_answer';
const line = JSON.stringify({ type: 'adjuster_answer', claim_id: r.claim_id, answer, at: new Date().toISOString() }) + '\n';
return [{ json: { claim_id: r.claim_id, adjuster_answer: answer },
          binary: { log: { data: Buffer.from(line, 'utf8').toString('base64'), mimeType: 'application/x-ndjson', fileName: 'decisions_log.jsonl' } } }];
