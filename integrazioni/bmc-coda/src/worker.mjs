const encoder = new TextEncoder();
const TYPES = new Set(['donation.created', 'donation.refunded',
  'recurring_donation.started', 'recurring_donation.updated', 'recurring_donation.cancelled']);

export async function hmac(secret, text) {
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret),
    {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
  return Array.from(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(text))))
    .map(n => n.toString(16).padStart(2, '0')).join('');
}

export async function authentic(raw, secret, signature) {
  if (!secret || !/^[0-9a-f]{64}$/i.test(signature || '')) return false;
  const expected = await hmac(secret, raw);
  let diff = 0;
  for (let i = 0; i < 64; i++) diff |= expected.charCodeAt(i) ^ signature.toLowerCase().charCodeAt(i);
  return diff === 0;
}

export function projectFromNote(note, codes) {
  const found = new Set();
  for (const m of String(note || '').matchAll(/#([a-z0-9-]+)\b/gi)) {
    const project = codes[m[1].toUpperCase()];
    if (project) found.add(project);
  }
  return found.size === 1 ? [...found][0] : null;
}

export async function supporterKey(data, secret) {
  const email = String(data.supporter_email || '').trim().toLowerCase();
  const id = data.supporter_id;
  const identity = email ? `email:${email}` : /^\d+$/.test(String(id)) && Number(id) > 0 ? `id:${id}` : null;
  return identity ? hmac(secret, identity) : null;
}

export async function acceptEvent(event, env) {
  if (!event || typeof event !== 'object' || typeof event.live_mode !== 'boolean'
    || !Number.isSafeInteger(event.created) || event.created < 0
    || !event.data || typeof event.data !== 'object') throw new Error('invalid-event');
  if (!event.live_mode) {
    await env.DB.prepare("INSERT INTO metadata(name,value) VALUES('last_test_at',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value")
      .bind(new Date().toISOString()).run();
    return {accepted: true, test: true};
  }
  if (!TYPES.has(event.type)) return {accepted: true, ignored: true};
  const data = event.data;
  if (!/^[1-9]\d{0,19}$/.test(String(data.id))) throw new Error('invalid-id');
  const codes = JSON.parse(env.PROJECT_CODES || '{}');
  const project = projectFromNote(data.support_note, codes);
  const supporter = await supporterKey(data, env.SUPPORTER_HASH_KEY);
  if (event.type.startsWith('donation.')) {
    const key = `payment:${data.id}`;
    const refund = event.type === 'donation.refunded' || data.status === 'refunded' || data.refunded === 'true';
    if (refund) {
      // Il rimborso è una tombstone: una consegna tardiva del pagamento non lo riattiva.
      await env.DB.prepare(`INSERT INTO contributions VALUES(?,?,?,'refunded',?)
        ON CONFLICT(record_key) DO UPDATE SET state='refunded',event_time=MAX(event_time,excluded.event_time)`)
        .bind(key, project, supporter, event.created).run();
    } else {
      if (data.status !== 'succeeded' || !Number.isFinite(data.amount) || data.amount <= 0)
        return {accepted: true, ignored: true};
      await env.DB.prepare(`INSERT INTO contributions VALUES(?,?,?,'paid',?) ON CONFLICT(record_key) DO NOTHING`)
        .bind(key, project, supporter, event.created).run();
    }
  } else {
    const state = event.type === 'recurring_donation.cancelled' || data.status === 'canceled'
      || data.canceled === 'true' ? 'canceled' : data.status === 'paused' || data.paused === 'true' ? 'paused'
      : data.status === 'active' && Number.isFinite(data.amount) && data.amount > 0 ? 'active' : 'inactive';
    await env.DB.prepare(`INSERT INTO contributions VALUES(?,?,?,?,?)
      ON CONFLICT(record_key) DO UPDATE SET
        project_id=COALESCE(excluded.project_id,contributions.project_id),
        supporter_key=COALESCE(excluded.supporter_key,contributions.supporter_key),
        state=excluded.state,event_time=excluded.event_time
      WHERE excluded.event_time>contributions.event_time
        OR (excluded.event_time=contributions.event_time AND excluded.state!='active')`)
      .bind(`subscription:${data.id}`, project, supporter, state, event.created).run();
  }
  return {accepted: true};
}

export async function publicCounts(env) {
  const projects = Object.fromEntries(Object.values(JSON.parse(env.PROJECT_CODES || '{}'))
    .map(id => [id, {supporters: 0}]));
  const {results} = await env.DB.prepare(`SELECT project_id,COUNT(DISTINCT supporter_key) AS supporters
    FROM contributions WHERE state IN ('paid','active') AND supporter_key IS NOT NULL
    GROUP BY project_id`).all();
  for (const row of results) if (Object.hasOwn(projects, row.project_id))
    projects[row.project_id].supporters = Number(row.supporters);
  return {projects};
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const headers = {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
      'Access-Control-Allow-Origin': env.PUBLIC_ORIGIN || 'https://sici29.github.io',
      'Vary': 'Origin', 'X-Content-Type-Options': 'nosniff'};
    const response = (body, status=200) => new Response(JSON.stringify(body), {status, headers});
    if (request.method === 'OPTIONS') return new Response(null, {status:204, headers: {
      ...headers, 'Access-Control-Allow-Methods':'GET', 'Access-Control-Max-Age':'3600'}});
    if (request.method === 'GET' && url.pathname === '/health') {
      const row = await env.DB.prepare("SELECT value FROM metadata WHERE name='last_test_at'").first();
      return response({ok:true, configured:!!(env.BMC_SIGNING_SECRET && env.SUPPORTER_HASH_KEY), last_test_at:row?.value || null});
    }
    if (request.method === 'GET' && url.pathname === '/public/support') {
      try { return response(await publicCounts(env)); } catch { return response({error:'unavailable'},503); }
    }
    if (url.pathname !== '/webhooks/bmc') return response({error:'not-found'},404);
    if (request.method !== 'POST') return response({error:'method-not-allowed'},405);
    if (!env.BMC_SIGNING_SECRET || !env.SUPPORTER_HASH_KEY) return response({error:'not-configured'},503);
    if (Number(request.headers.get('content-length')) > 65536) return response({error:'too-large'},413);
    const reader = request.body?.getReader();
    if (!reader) return response({error:'empty-body'},400);
    const chunks = []; let length=0;
    while (true) {
      const {value,done} = await reader.read(); if (done) break;
      length += value.length;
      if (length > 65536) { await reader.cancel(); return response({error:'too-large'},413); }
      chunks.push(value);
    }
    const body = new Uint8Array(length); let offset=0;
    for (const chunk of chunks) {body.set(chunk,offset);offset+=chunk.length;}
    const raw = new TextDecoder().decode(body);
    if (!await authentic(raw,env.BMC_SIGNING_SECRET,request.headers.get('x-signature-sha256')))
      return response({error:'invalid-signature'},401);
    let event; try {event=JSON.parse(raw);} catch {return response({error:'invalid-json'},400);}
    try {return response(await acceptEvent(event,env));}
    catch (e) {return response({error:e.message.startsWith('invalid-')?'invalid-event':'temporary-error'},
      e.message.startsWith('invalid-')?400:503);}
  }
};
