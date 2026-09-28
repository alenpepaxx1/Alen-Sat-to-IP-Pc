/* Copyright © 2026 Alen Pepa. */
/* Localizes application-owned text nodes in place; never rebuilds forms or players. */
(function(root,factory){const api=factory(root);root.AlenI18n=api;if(typeof module==='object'&&module.exports)module.exports=api;})(globalThis,function(root){
 'use strict';
 const catalog=root.AlenTranslations||{},codes=['en','sq','de'],locales={en:'en-GB',sq:'sq-AL',de:'de-DE'};
 let language='en';
 try{const saved=root.localStorage?.getItem('alen-stb-language');language=codes.includes(saved)?saved:(root.navigator?.language||'en').slice(0,2);if(!codes.includes(language))language='en';}catch{}
 const records=new WeakMap();
 const attributes=['title','aria-label','placeholder','alt'];
 const escapeRx=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
 const patterns=Object.entries(catalog).filter(([key])=>/\{\w+\}/.test(key)).sort((a,b)=>b[0].length-a[0].length).map(([key,entry])=>{
  const names=[...key.matchAll(/\{(\w+)\}/g)].map(match=>match[1]);
  return {rx:new RegExp('^'+key.split(/\{\w+\}/g).map(escapeRx).join('(.+?)')+'$'),entry,names};
 });
 function tr(value){
  if(typeof value!=='string'||language==='en')return value;
  const body=value.trim(),entry=catalog[body];
  let translated=entry?.[language];
  if(!translated){for(const pattern of patterns){const match=body.match(pattern.rx);if(match){const args=Object.fromEntries(pattern.names.map((name,i)=>[name,name==='field'?(catalog[match[i+1]]?.[language]||match[i+1]):match[i+1]]));translated=pattern.entry[language].replace(/\{(\w+)\}/g,(_,name)=>args[name]);break;}}}
  return translated?value.slice(0,value.indexOf(body))+translated+value.slice(value.indexOf(body)+body.length):value;
 }
 function transform(node,key,current,write){
  let record=records.get(node);if(!record){record={};records.set(node,record);}
  let item=record[key];if(!item||current!==item.result)item={source:current,result:current};
  const result=tr(item.source);item.result=result;record[key]=item;
  if(current!==result)write(result);
 }
 function translateNode(node){
  if(node.nodeType===3){if(node.parentElement?.closest('[translate="no"],script,style,textarea,code,pre'))return;transform(node,'text',node.nodeValue,v=>node.nodeValue=v);return;}
  if(node.nodeType!==1&&node.nodeType!==9&&node.nodeType!==11)return;
  if(node.nodeType===1){
   if(node.closest('[translate="no"],script,style,textarea,code,pre'))return;
   for(const key of attributes){if(node.hasAttribute(key))transform(node,key,node.getAttribute(key),v=>node.setAttribute(key,v));}
   if(node.tagName==='OPTION'&&!node.hasAttribute('value'))node.setAttribute('value',node.textContent);
   if(node.hasAttribute('data-date')){const date=new Date(node.getAttribute('data-date'));if(Number.isFinite(+date))node.textContent=date.toLocaleString(locales[language]);return;}
  }
  for(const child of Array.from(node.childNodes||[]))translateNode(child);
 }
 function setLanguage(code){
  if(!codes.includes(code))return false;language=code;
  try{root.localStorage?.setItem('alen-stb-language',code);}catch{}
  if(root.document){root.document.documentElement.lang=code;translateNode(root.document.body);root.document.title=tr('Alen STB · Receiver control');const select=root.document.querySelector('#languageSelect');if(select)select.value=code;for(const field of root.document.querySelectorAll?.('input,select,textarea')||[])field.setCustomValidity?.('');}
  return true;
 }
 function start(){
  if(!root.document?.body)return;
  setLanguage(language);
  root.document.querySelector('#languageSelect')?.addEventListener('change',e=>setLanguage(e.target.value));
  root.document.addEventListener?.('invalid',event=>{
   const field=event.target;if(!field.validity||!field.setCustomValidity)return;
   const v=field.validity;
   const message=v.valueMissing?'Please fill out this field.':v.typeMismatch?'Please enter a valid address.':v.patternMismatch?'Please use the required format.':v.rangeUnderflow||v.rangeOverflow?'Please enter a value within the allowed range.':v.stepMismatch||v.badInput?'Please enter a valid number.':'Please check this value.';
   field.setCustomValidity(tr(message));
  },true);
  for(const name of ['input','change'])root.document.addEventListener?.(name,event=>event.target.setCustomValidity?.(''),true);
  if(root.MutationObserver)new root.MutationObserver(changes=>{for(const change of changes){if(change.type==='attributes')translateNode(change.target);else if(change.type==='characterData')translateNode(change.target);else for(const node of change.addedNodes)translateNode(node);}}).observe(root.document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attributes});
 }
 return {tr,setLanguage,translateNode,start,get language(){return language;},get locale(){return locales[language];},catalog};
});
if(typeof document!=='undefined')AlenI18n.start();
