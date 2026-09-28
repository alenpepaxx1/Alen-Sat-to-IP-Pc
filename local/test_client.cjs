/* Copyright © 2026 Alen Pepa. */
const fs=require('node:fs');const vm=require('node:vm');const assert=require('node:assert/strict');const path=require('node:path');
const staticIds=['nav','crumb','receiver-icon','headerConnect','modeBadge','deviceName','deviceState','footerMode','notice','content','dialog','dialogContent','toast'];
const nodes=Object.fromEntries(staticIds.map(id=>['#'+id,{innerHTML:'',textContent:'',open:false,isConnected:true,addEventListener(){},classList:{add(){},remove(){}},showModal(){this.open=true},close(){this.open=false}}]));
const context=vm.createContext({AlenI18n:require('../dist/i18n.js'),AlenCore:require('../dist/core.js'),AbortController,console,URL,AbortSignal,structuredClone,crypto:globalThis.crypto,setTimeout,clearTimeout,setInterval,clearInterval,localStorage:{removeItem(){}},location:{hash:'',href:'http://localhost/',protocol:'http:'},document:{querySelector:s=>nodes[s]||null,querySelectorAll:()=>[],body:{dataset:{}},addEventListener(){}},window:{addEventListener(){},removeEventListener(){}},fetch:async()=>{throw Error('Unexpected network request while disconnected');}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist/app.js'),'utf8'),context);
(async()=>{
 assert.equal(vm.runInContext('state.channels.length',context),0);
 assert.equal(vm.runInContext('state.snr',context),null);
 assert.equal(nodes['#modeBadge'].textContent,'Receiver offline');
 for(const view of ['channels','manage','epg','remote','timers','satfinder','media','settings','integrations']){
  vm.runInContext(`state.view=${JSON.stringify(view)};render()`,context);
  assert(!/Top Channel|13\.2|DEMO|Simulated/.test(nodes['#content'].innerHTML));
 }
 await assert.rejects(vm.runInContext("command('remote','/api/remote',{key:'UP'})",context),/connected receiver/);
 context.fetch=async()=>({ok:true,json:async()=>({})});
 vm.runInContext("bridge='http://localhost:8787';state.mode='live';state.capabilities=['remote']",context);
 await assert.rejects(vm.runInContext("command('remote','/api/remote',{key:'UP'})",context),/acknowledge/);
 context.fetch=async()=>({ok:true,json:async()=>({ok:true})});
 assert.equal((await vm.runInContext("command('remote','/api/remote',{key:'UP'})",context)).ok,true);
 vm.runInContext('clearReceiver()',context);
 context.location.hostname='127.0.0.1';context.location.origin='http://127.0.0.1:8787';
 context.fetch=async(url,options)=>{assert.equal(url,'http://127.0.0.1:8787/api/bootstrap');assert.equal(options.headers['X-Alen-Bootstrap'],'1');return {ok:true,json:async()=>({protocol:'alen-stb-bridge-v1',automatic:true,bridge:'http://127.0.0.1:8787',token:'local-test-token-with-enough-characters',target:null})}};
 assert.equal(await vm.runInContext('autoBootstrap()',context),true);
 assert.equal(vm.runInContext('automaticBridge && bridgeConnected',context),true);
 assert.equal(vm.runInContext('connected()',context),false);
 assert.equal(vm.runInContext('state.channels.length',context),0);


 // A late pairing response must not reverse the user's disconnect.
 let release;
 context.fetch=()=>new Promise(resolve=>release=resolve);
 const pending=vm.runInContext('autoBootstrap()',context);
 vm.runInContext('actions.disconnect()',context);
 release({ok:true,json:async()=>({protocol:'alen-stb-bridge-v1',automatic:true,bridge:context.location.origin,token:'late-test-token-with-enough-characters',target:null})});
 assert.equal(await pending,false);
 assert.equal(vm.runInContext('bridgeConnected || automaticBridge',context),false);
 assert.equal(vm.runInContext('token',context),'');
 // A failed re-pair cannot retain a misleading ready/connected indicator.
 vm.runInContext("automaticBridge=true;bridgeConnected=true;bridge=location.origin;token='previous-token'",context);
 context.fetch=async()=>({ok:false});
 assert.equal(await vm.runInContext('autoBootstrap()',context),false);
 assert.equal(vm.runInContext('bridgeConnected || automaticBridge',context),false);
 assert.equal(vm.runInContext("has('remote')",context),false);
 vm.runInContext("state.mode='live';state.capabilities=['stream'];state.channels=[{id:'a',name:'A'},{id:'b',name:'B'}];actions.select({dataset:{id:'b'}})",context);
 assert.equal(vm.runInContext('state.selected',context),'b');
 vm.runInContext('clearReceiver()',context);
 let paused=0;
 nodes['#streamPlayer']={pause(){paused++}};
 nodes['#callAlert']={hidden:true,textContent:''};
 context.fetch=async()=>({ok:true,json:async()=>({paired:true,revision:9,events:[{id:9,callId:'real-event-contract',state:'ringing'}]})});
 vm.runInContext("bridge='http://localhost:8787';bridgeConnected=true;token='test'",context);
 await vm.runInContext('pollCalls(callEpoch)',context);
 assert.equal(paused,1);
 assert.equal(nodes['#callAlert'].hidden,false);
 assert.equal(vm.runInContext('callAfter',context),9);
 delete nodes['#streamPlayer'];
 vm.runInContext('stopCallAlerts()',context);
 assert.equal(nodes['#callAlert'].hidden,true);
 // Unsupported Notification constructors must not discard later call events.
 context.Notification=class { static permission='granted'; constructor(){throw new TypeError('Use a service worker');} };
 context.fetch=async()=>({ok:true,json:async()=>({paired:true,revision:12,events:[
  {id:10,callId:'first',state:'ringing'}, {id:11,callId:'second',state:'ringing'}, {id:12,callId:'first',state:'ended'}
 ]})});
 await vm.runInContext('pollCalls(callEpoch)',context);
 assert.equal(nodes['#callAlert'].hidden,false,'A second active call must keep the banner visible');
 assert.equal(vm.runInContext('ringingCalls.size',context),1);
 context.fetch=async()=>({ok:true,json:async()=>({paired:true,revision:13,events:[{id:13,callId:'second',state:'ended'}]})});
 await vm.runInContext('pollCalls(callEpoch)',context);
 assert.equal(nodes['#callAlert'].hidden,true);
 // Permission request rejection must not prevent in-app polling.
 context.Notification={permission:'default',requestPermission:async()=>{throw Error('Unsupported');}};
 await vm.runInContext('enableCallAlerts()',context);
 assert.equal(vm.runInContext('callTimer!==null',context),true);
 vm.runInContext('stopCallAlerts()',context);
 // Cancelled playback releases the issued ticket using its original bridge/token.
 const stops=[];
 context.fetch=async(url,options)=>{stops.push({url,options});return {ok:true};};
 await vm.runInContext("watchResponse({url:'/live/cancelled',streamId:'cancelled'},{base:'http://192.168.1.2:8787',token:'old-token'},()=>false)",context);
 assert.equal(stops[0].url,'http://192.168.1.2:8787/api/satip/stop');
 assert.equal(stops[0].options.headers.Authorization,'Bearer old-token');
 assert.equal(JSON.parse(stops[0].options.body).streamId,'cancelled');
 // A dialog change while the previous stream stops must not reopen the player.
 let finishStop;
 context.pendingStop=new Promise(resolve=>{finishStop=resolve;});
 vm.runInContext('stopStreamPromise=pendingStop',context);
 const playback=vm.runInContext("watchResponse({url:'/live/late',streamId:'late'},{base:bridge,token},()=>true)",context);
 vm.runInContext('dialogEpoch++',context);
 finishStop();
 await assert.rejects(playback,/Connection changed before playback/);
 assert.equal(JSON.parse(stops.at(-1).options.body).streamId,'late');
 assert.equal(vm.runInContext('activeStream',context),null);
 // Invalid URLs also release their ticket, rather than occupying a pending slot.
 await assert.rejects(vm.runInContext("watchResponse({url:'javascript:bad',streamId:'invalid'},{base:bridge,token},()=>true)",context),/HTTP/);
 assert.equal(JSON.parse(stops.at(-1).options.body).streamId,'invalid');
 console.log('PASS: empty startup, all disconnected views, capability gating, acknowledgement enforcement, local automatic pairing, cancellation of late pairing and failure-state cleanup.');
})().catch(e=>{console.error(e);process.exitCode=1});
