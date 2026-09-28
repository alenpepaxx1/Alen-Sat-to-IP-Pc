/* Copyright © 2026 Alen Pepa. */
const test=require('node:test');const assert=require('node:assert/strict');
const core=require('../dist/core.js');
test('channel boundary rejects duplicate IDs and non-boolean locks',()=>{
 assert.throws(()=>core.channels([{id:'a',name:'One'},{id:'a',name:'Two'}]),/duplicate/);
 assert.throws(()=>core.channels([{id:'a',name:'One',locked:'false'}]),/locked/);
 assert.throws(()=>core.channels([null]),/channel/);
 assert.equal(core.channels([{id:'a',name:'One',locked:false}])[0].locked,false);
});
test('timer boundaries preserve the instant and use UTC',()=>{
 const now=Date.now();const future=new Date(now+3600000);
 const value=core.timerPayload({title:'Programme',channelId:'a',start:future.toISOString(),duration:'60',type:'Record'},'id',now);
 assert.equal(value.start,future.toISOString());assert.equal(value.duration,60);
 assert.throws(()=>core.timerPayload({...value,start:'not a date'},'id',now),/valid start/);
 assert.throws(()=>core.timerPayload({...value,duration:'1.5'},'id',now),/whole minutes/);
 assert.match(core.localDate(future),/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
});
test('timer IDs work without secure-context randomUUID',()=>{
 const id=core.identifier({getRandomValues:b=>{b.fill(12);return b;}});
 assert.match(id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});
test('blank and credential-bearing stream URLs cannot play the app itself',()=>{
 assert.throws(()=>core.streamUrl('','http://localhost:8787'),/stream URL/);
 assert.throws(()=>core.streamUrl('http://user:secret@192.168.1.1/live'),/credentials/);
 assert.equal(core.streamUrl('/live.mp4','http://192.168.1.10:8787').href,'http://192.168.1.10:8787/live.mp4');
});
test('connection reset discards late responses even if transport ignores abort',async()=>{
 const session=new core.Session();let resolve;
 const pending=session.run(()=>new Promise(r=>resolve=r));session.reset();resolve({channels:['stale']});
 await assert.rejects(pending,/stale response/);assert.equal(session.controllers.size,0);
});
test('timeouts abort requests and clear controller bookkeeping',async()=>{
 const session=new core.Session();
 await assert.rejects(session.run(signal=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted')))),5),/aborted/);
 assert.equal(session.controllers.size,0);
});
