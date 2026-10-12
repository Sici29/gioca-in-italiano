import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker, {acceptEvent, publicCounts, projectFromNote, authentic} from '../src/worker.mjs';

function env() {
  const sqlite = new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
  return {BMC_SIGNING_SECRET:'test-signing-secret', SUPPORTER_HASH_KEY:'separate-private-key',
    PROJECT_CODES:JSON.stringify({AION2:'aion2',ALTRO:'altro'}),
    DB:{prepare(sql) {let args=[];const statement=sqlite.prepare(sql);return {
      bind(...values){args=values;return this;},
      async run(){return statement.run(...args);},
      async all(){return {results:statement.all(...args)};},
      async first(){return statement.get(...args)||null;}
    };}}};
}
function event(overrides={},data={}) {
  return {event_id:1,type:'donation.created',live_mode:true,created:100,attempt:1,
    data:{id:1,status:'succeeded',amount:5,currency:'USD',supporter_email:'alex@example.com',
      supporter_name:'Private name',support_note:'#AION2',...data},...overrides};
}
function signed(body,e) {
  const raw=JSON.stringify(body);
  return new Request('https://worker.example/webhooks/bmc',{method:'POST',body:raw,headers:{
    'x-signature-sha256':createHmac('sha256',e.BMC_SIGNING_SECRET).update(raw).digest('hex')}});
}
test('Firma verificata sul corpo originale, firme errate o troncate rifiutate',async()=>{
  const raw='{"x":1}';const sig=createHmac('sha256','secret').update(raw).digest('hex');
  assert.equal(await authentic(raw,'secret',sig),true);
  assert.equal(await authentic(raw+' ','secret',sig),false);
  assert.equal(await authentic(raw,'secret','bad'),false);
  assert.equal(await authentic(raw,'secret',sig.toUpperCase()),true);
});
test('Una persona per gioco, senza peso per importo o pagamenti ripetuti',async()=>{
  const e=env();await acceptEvent(event(),e);await acceptEvent(event(),e);
  await acceptEvent(event({}, {id:2,amount:500,currency:'EUR',supporter_email:' ALEX@example.com '}),e);
  assert.equal((await publicCounts(e)).projects.aion2.supporters,1);
});
test('Rimborso gestito, anche se arriva prima del pagamento',async()=>{
  const e=env();await acceptEvent(event({type:'donation.refunded',created:200}),e);
  await acceptEvent(event(),e);assert.equal((await publicCounts(e)).projects.aion2.supporters,0);
  await acceptEvent(event({}, {id:2}),e);assert.equal((await publicCounts(e)).projects.aion2.supporters,1);
  await acceptEvent(event({type:'donation.refunded',created:300},{id:2}),e);
  assert.equal((await publicCounts(e)).projects.aion2.supporters,0);
});
test('Test della piattaforma accettato senza gonfiare i conteggi',async()=>{
  const e=env();const r=await worker.fetch(signed(event({live_mode:false}),e),e);
  assert.equal(r.status,200);assert.equal((await r.json()).test,true);
  assert.equal((await publicCounts(e)).projects.aion2.supporters,0);
  const health=await worker.fetch(new Request('https://worker.example/health'),e);
  assert.ok((await health.json()).last_test_at);
});
test('La cancellazione prevale sui vecchi eventi ripetuti',async()=>{
  const e=env();const start=event({type:'recurring_donation.started'},{status:'active'});
  await acceptEvent(start,e);assert.equal((await publicCounts(e)).projects.aion2.supporters,1);
  await acceptEvent(event({type:'recurring_donation.cancelled',created:200},{status:'canceled'}),e);
  await acceptEvent(start,e);assert.equal((await publicCounts(e)).projects.aion2.supporters,0);
});
test('Stesso istante: cancellazione prevale, senza dipendere dall’ordine',async()=>{
  for(const firstCancelled of [true,false]) {
    const e=env();const a=event({type:'recurring_donation.started'},{status:'active'});
    const b=event({type:'recurring_donation.cancelled'},{status:'canceled'});
    await acceptEvent(firstCancelled?b:a,e);await acceptEvent(firstCancelled?a:b,e);
    assert.equal((await publicCounts(e)).projects.aion2.supporters,0);
  }
});
test('Nota senza codice o con due giochi non attribuita arbitrariamente',()=>{
  const codes={AION2:'aion2',ALTRO:'altro'};
  assert.equal(projectFromNote('Per #aion2!',codes),'aion2');
  assert.equal(projectFromNote('#AION2 #ALTRO',codes),null);
  assert.equal(projectFromNote('#AION2FAKE',codes),null);
  assert.equal(projectFromNote('Grazie',codes),null);
});
test('Output pubblico e database escludono nomi, email e note originali',async()=>{
  const e=env();await acceptEvent(event(),e);
  const pub=JSON.stringify(await publicCounts(e));
  const rows=JSON.stringify((await e.DB.prepare('SELECT * FROM contributions').all()).results);
  for(const text of [pub,rows]) {
    assert.ok(!text.includes('alex@example.com'));assert.ok(!text.includes('Private name'));assert.ok(!text.includes('#AION2'));
  }
  assert.deepEqual(JSON.parse(pub),{projects:{aion2:{supporters:1},altro:{supporters:0}}});
});
test('Webhook senza firma non muta il database; corpo troppo grande rifiutato',async()=>{
  const e=env();const bad=await worker.fetch(new Request('https://worker.example/webhooks/bmc',
    {method:'POST',body:JSON.stringify(event())}),e);
  assert.equal(bad.status,401);
  assert.equal((await publicCounts(e)).projects.aion2.supporters,0);
  const large=await worker.fetch(new Request('https://worker.example/webhooks/bmc',{method:'POST',body:'x'.repeat(65537)}),e);
  assert.equal(large.status,413);
});
test('Pagamento non riuscito e anonimo senza identità non incrementano il conteggio',async()=>{
  const e=env();await acceptEvent(event({}, {status:'failed'}),e);
  await acceptEvent(event({}, {id:2,supporter_email:undefined,supporter_id:undefined}),e);
  assert.equal((await publicCounts(e)).projects.aion2.supporters,0);
});
