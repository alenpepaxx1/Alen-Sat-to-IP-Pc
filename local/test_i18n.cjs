/* Copyright © 2026 Alen Pepa. */
const assert=require('node:assert/strict'),test=require('node:test'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'..');
class Element {
 constructor(tag,attrs={},children=[]){this.nodeType=1;this.tagName=tag.toUpperCase();this.attrs={...attrs};this.childNodes=children;for(const child of children)child.parentElement=this;this.value='';}
 closest(){for(let node=this;node;node=node.parentElement)if(node.attrs.translate==='no'||['SCRIPT','STYLE','TEXTAREA','CODE','PRE'].includes(node.tagName))return node;return null;}
 hasAttribute(k){return k in this.attrs;}getAttribute(k){return this.attrs[k];}setAttribute(k,v){this.attrs[k]=v;}
 get textContent(){return this.childNodes.map(n=>n.nodeValue??n.textContent).join('');}
 set textContent(v){this.childNodes=[text(v)];this.childNodes[0].parentElement=this;}
 addEventListener(name,fn){this[name]=fn;}
}
const text=v=>({nodeType:3,nodeValue:v});
function setup(stored,locale='en-US'){
 const storage={};if(stored)storage['alen-stb-language']=stored;
 const select=new Element('select');const body=new Element('body');let observer;
 const c=vm.createContext({console,navigator:{language:locale},localStorage:{getItem:k=>storage[k],setItem:(k,v)=>storage[k]=v},document:{body,documentElement:{},title:'',querySelector:s=>s==='#languageSelect'?select:null},MutationObserver:class{constructor(fn){observer=fn;}observe(){}}});
 vm.runInContext(fs.readFileSync(root+'/dist/translations.js','utf8'),c);vm.runInContext(fs.readFileSync(root+'/dist/i18n.js','utf8'),c);
 return {ui:c.AlenI18n,body,select,storage,c,mutate:changes=>observer(changes)};
}
test('all catalog entries contain all three languages with matching placeholders',()=>{
 const {ui}=setup();assert(Object.keys(ui.catalog).length>=500);
 for(const [key,row] of Object.entries(ui.catalog))for(const lang of ['en','sq','de']){
  assert.equal(typeof row[lang],'string',key+' '+lang);assert(row[lang].trim());
  assert.deepEqual([...row[lang].matchAll(/\{\w+\}/g)].map(m=>m[0]).sort(),[...key.matchAll(/\{\w+\}/g)].map(m=>m[0]).sort());
 }
});
test('live switch preserves nodes, protocol option values, form inputs and receiver names',()=>{
 const {ui,body}=setup();const node=text('Receiver settings'),protectedText=text('News');
 const input=new Element('input',{placeholder:'Channel name'});input.value='My personal channel';
 const option=new Element('option',{},[text('Record')]);const protectedNode=new Element('strong',{translate:'no'},[protectedText]);
 body.childNodes=[new Element('h1',{},[node]),input,option,protectedNode];
 for(const lang of ['sq','de','en']){ui.setLanguage(lang);assert.equal(node.nodeValue,ui.catalog['Receiver settings'][lang]);assert.equal(input.value,'My personal channel');assert.equal(option.attrs.value,'Record');assert.equal(protectedText.nodeValue,'News');assert.equal(body.childNodes[1],input);}
});
test('selection persists, uses browser preference and tolerates blocked storage',()=>{
 const a=setup(undefined,'sq-AL');assert.equal(a.ui.language,'sq');a.ui.setLanguage('de');assert.equal(a.storage['alen-stb-language'],'de');
 assert.equal(setup(a.storage['alen-stb-language']).ui.language,'de');assert.equal(setup('bad','fr-FR').ui.language,'en');
 a.c.localStorage.setItem=()=>{throw Error('blocked');};assert.doesNotThrow(()=>a.ui.setLanguage('sq'));assert.equal(a.ui.setLanguage('fr'),false);
});
test('asynchronous messages and placeholders localize without translating parameter values',()=>{
 const {ui,body,mutate}=setup('de');const p=new Element('p',{},[text('Receiver connected.')]);body.childNodes.push(p);
 mutate([{type:'childList',addedNodes:[p]}]);assert.equal(p.textContent,'Receiver verbunden.');
 p.textContent='Channel not found.';mutate([{type:'childList',addedNodes:p.childNodes}]);assert.equal(p.textContent,'Sender nicht gefunden.');
 assert.equal(ui.tr('Receiver tuned to News'),'Receiver auf News umgeschaltet');
 assert.equal(ui.tr('Invalid frequency in MHz: expected 300–13000.'),'Ungültiger Wert für Frequenz in MHz: erwartet 300–13000.');
 ui.setLanguage('en');assert.equal(p.textContent,'Channel not found.');
});
test('date nodes follow selected locale and timer payload remains English protocol values',()=>{
 const {ui,body}=setup();const time=new Element('time',{'data-date':'2026-09-27T12:00:00Z'});body.childNodes=[time];
 ui.setLanguage('de');assert.equal(time.textContent,new Date('2026-09-27T12:00:00Z').toLocaleString('de-DE'));
 const core=require('../dist/core.js');const payload=core.timerPayload({title:'Aufnahme',channelId:'1',start:'2036-09-27T12:00:00Z',duration:'30',type:'Record'},'x');assert.equal(payload.type,'Record');
});
