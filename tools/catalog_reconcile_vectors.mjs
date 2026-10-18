// Preload the normal vector CLI; retain its corpus/model-space algorithms.
// Only this exact Voyage transport is wrapped in the original logical budget.
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';

const generation = process.env.CATALOG_VECTOR_OPERATION === 'generation';
const state = generation ? process.env.OFFLINE_AI_STATE : process.env.CATALOG_RECONCILE_STATE;
if (!state) throw Error('catalog_reconcile_vector_state_required');
const nativeFetch = globalThis.fetch;
function bridge(action, packet) {
  const raw = execFileSync(process.env.PYTHON || 'python',
    ['-m', 'tools.catalog_reconcile_spend', action, '--state', state, ...(generation ? ['--generation'] : [])],
    {input:JSON.stringify(packet), encoding:'utf8', maxBuffer:26 * 1024 * 1024});
  return JSON.parse(raw);
}
function acceptedResponse(cache) {
  const saved = JSON.parse(readFileSync(cache, 'utf8'));
  return new Response(JSON.stringify(saved.payload), {status:saved.status,
    headers:{'content-type':'application/json', 'request-id':saved.request_id || ''}});
}
globalThis.fetch = async (url, options) => {
  if (String(url) !== 'https://api.voyageai.com/v1/embeddings' || options?.method !== 'POST') {
    throw Error('catalog_reconcile_unexpected_provider_transport');
  }
  const reservation = bridge('reserve', {url:String(url), body:options.body});
  if (reservation.status === 'cached') {
    return acceptedResponse(reservation.cache);
  }
  const response = await nativeFetch(url, options);
  if (response.status !== 200) throw Error('catalog_reconcile_provider_http_' + response.status);
  const raw = await response.text();
  if (Buffer.byteLength(raw) > 24 * 1024 * 1024) throw Error('catalog_reconcile_provider_response_limit');
  let payload;
  try { payload = JSON.parse(raw); }
  catch { throw Error('catalog_reconcile_invalid_provider_json'); }
  const requestId = response.headers.get('request-id') || response.headers.get('x-request-id');
  // Any transport, malformed response, or incomplete persist leaves the
  // conservative reservation charged and prohibits an automatic redispatch.
  const accepted = bridge('finish', {key:reservation.key, token:reservation.token,
    status:response.status, payload, request_id:requestId});
  return acceptedResponse(accepted.cache);
};
