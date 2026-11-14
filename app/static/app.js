'use strict';
const $ = id => document.getElementById(id);
const state = {pdfs:[], infos:[], seals:[], originals:[], stamps:[], active:0, page:1, sourceUrl:null, currentSize:null, loadSerial:0, sealCache:new Map(), seam:{enabled:false,image_index:0,position:'right',size_mm:40,scope:'all',pages:'',max_pages:12,position_percent:50,opacity:.95,white_to_alpha:true,threshold:245}};
const mm2pt = 72/25.4;
const esc = v => String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
function notice(text,error=false){const t=$('toast'); t.textContent=text; t.className='toast show'+(error?' error':'');clearTimeout(notice.timer);notice.timer=setTimeout(()=>t.classList.remove('show'),4500)}
function readable(bytes){return bytes<1024*1024?`${Math.round(bytes/1024)} KB`:`${(bytes/1024/1024).toFixed(1)} MB`}
function currentInfo(){return state.infos[state.active]}
function pageWidth(){return currentInfo()?.sizes[state.page-1]?.width || 595}
function validDownload(){return state.pdfs.length>0&&state.seals.length>0&&(state.stamps.length>0||state.seam.enabled)}
function refreshExport(){ $('export').disabled=!validDownload() }
function defaultStamp(){return {image_index:0,scope:'last',pages:'',size_mm:40,x:.5,y:.7,rotation:0,opacity:.95,white_to_alpha:true,threshold:245}}

function viewPDFList(){
 const list=$('pdf-list'); list.innerHTML=state.pdfs.map((f,i)=>`<div class="file-item ${i===state.active?'active':''}" data-index="${i}"><span class="file-icon">PDF</span><span class="file-name" title="${esc(f.name)}">${esc(f.name)}</span><span class="file-meta">${state.infos[i]?.pages??'…'}页</span><button type="button" class="mini-remove" title="删除" data-remove-pdf="${i}">×</button></div>`).join('');
 list.querySelectorAll('[data-index]').forEach(el=>el.addEventListener('click',e=>{if(e.target.closest('button'))return;state.active=Number(el.dataset.index);state.page=1;viewPDFList();viewFileSelect();renderPDF()}));
 list.querySelectorAll('[data-remove-pdf]').forEach(el=>el.addEventListener('click',e=>{e.stopPropagation();const idx=+el.dataset.removePdf;state.pdfs.splice(idx,1);state.infos.splice(idx,1);state.active=clamp(state.active,0,Math.max(0,state.pdfs.length-1));state.page=1;viewPDFList();viewFileSelect();renderPDF();refreshExport()}));
}
function viewFileSelect(){
 const sel=$('preview-file');sel.innerHTML=state.pdfs.length?state.pdfs.map((f,i)=>`<option value="${i}">${esc(f.name)}</option>`).join(''):'<option>尚未选择文件</option>';sel.disabled=!state.pdfs.length;sel.value=String(state.active);
 const info=currentInfo();$('current-page').textContent=info?state.page:'—';$('total-pages').textContent=info?info.pages:'—';$('prev-page').disabled=!info||state.page<=1;$('next-page').disabled=!info||state.page>=info.pages;
 $('document-info').textContent=info?`${info.pages} 页 · ${readable(state.pdfs[state.active].size)}${info.has_signatures?' · 检测到数字签名':''}`:'尚未载入文档';
}
async function inspectFile(f){const form=new FormData();form.append('file',f);form.append('password',$('input-password').value);const r=await fetch('/api/inspect',{method:'POST',body:form});if(!r.ok){const j=await r.json().catch(()=>({detail:'无法读取PDF'}));throw Error(j.detail)}return r.json()}
async function addPDFs(files){
 const list=Array.from(files).filter(f=>/\.pdf$/i.test(f.name)||f.type==='application/pdf'); if(!list.length){notice('请选择 PDF 文件。',true);return}
 for(const file of list){if(state.pdfs.length>=12){notice('单批最多 12 份 PDF。',true);break}if(file.size>50*1024*1024){notice(`${file.name} 超过 50 MB。`,true);continue}
  try{const info=await inspectFile(file);state.pdfs.push(file);state.infos.push(info);if(info.has_signatures)notice(`${file.name} 含数字签名，修改后可能失效。`,true)}catch(err){notice(`${file.name}：${err.message}`,true)}
 }
 if(state.pdfs.length===1)state.active=0;
 viewPDFList();viewFileSelect();refreshExport();renderPDF();$('pdf-files').value='';
}
async function addSeals(files){
 for(const f of files){if(state.seals.length>=12){notice('最多使用 12 张印章图片。',true);break}if(f.size>8*1024*1024){notice(`${f.name} 超过 8 MB。`,true);continue}if(!f.type.startsWith('image/')&&!/\.(png|jpe?g|webp)$/i.test(f.name)){notice('请选择图片文件。',true);continue}
  state.seals.push(f);state.originals.push(URL.createObjectURL(f));
 }
 if(state.seals.length&&!state.stamps.length&&!state.seam.enabled)state.stamps.push(defaultStamp());
 viewSeals();viewStamps();viewSeam();refreshExport();drawOverlays();$('seal-files').value='';
}
function viewSeals(){
 const list=$('seal-list');list.innerHTML=state.seals.map((f,i)=>`<div class="seal-item"><img class="seal-thumb" src="${state.originals[i]}" alt=""><span class="seal-title" title="${esc(f.name)}">${esc(f.name)}</span><button class="mini-remove" data-rm-seal="${i}" title="删除">×</button></div>`).join('');
 list.querySelectorAll('[data-rm-seal]').forEach(btn=>btn.addEventListener('click',()=>{
  const i=+btn.dataset.rmSeal; URL.revokeObjectURL(state.originals[i]);state.seals.splice(i,1);state.originals.splice(i,1);state.stamps=state.stamps.filter(s=>s.image_index!==i);state.stamps.forEach(s=>{if(s.image_index>i)s.image_index--});if(state.seam.image_index>=state.seals.length)state.seam.image_index=0;state.sealCache.forEach(u=>URL.revokeObjectURL(u));state.sealCache.clear();viewSeals();viewStamps();viewSeam();refreshExport();drawOverlays();
 }));
}
function sealOptions(sel){return state.seals.map((f,i)=>`<option value="${i}" ${sel===i?'selected':''}>${esc(f.name)}</option>`).join('')||'<option value="0">请先添加印章</option>'}
function scopeOptions(scope){return [['all','全部页面'],['first','第一页'],['last','最后一页'],['odd','奇数页'],['even','偶数页'],['custom','指定页码']].map(([a,b])=>`<option value="${a}" ${scope===a?'selected':''}>${b}</option>`).join('')}
function viewStamps(){
 const content=$('stamps-container');content.innerHTML=state.stamps.map((s,i)=>`<div class="stamp-card" data-stamp="${i}"><div class="stamp-header"><span class="stamp-index">${i+1}</span> 普通公章 <button class="mini-remove" data-delete-stamp="${i}" title="删除">×</button></div><div class="form-grid">
 <label class="full">印章图片<select data-key="image_index">${sealOptions(s.image_index)}</select></label>
 <label>加盖页面<select data-key="scope">${scopeOptions(s.scope)}</select></label><label>直径 / 宽度（mm）<input data-key="size_mm" type="number" min="8" max="180" value="${s.size_mm}"></label>
 <label class="full" ${s.scope==='custom'?'':'hidden'} data-custom>指定页码<input data-key="pages" value="${esc(s.pages)}" placeholder="如 1,3-5"></label>
 <label>横向位置（%）<input data-key="x" type="number" min="0" max="100" value="${Math.round(s.x*100)}"></label><label>纵向位置（%）<input data-key="y" type="number" min="0" max="100" value="${Math.round(s.y*100)}"></label>
 <label>旋转角度（°）<input data-key="rotation" type="number" min="-180" max="180" value="${s.rotation}"></label><label>不透明度（%）<input data-key="opacity" type="number" min="5" max="100" value="${Math.round(s.opacity*100)}"></label>
 <label class="full toggle-row"><input data-key="white_to_alpha" type="checkbox" ${s.white_to_alpha?'checked':''}> 自动去除白色背景</label>
 </div></div>`).join('');
 content.querySelectorAll('[data-delete-stamp]').forEach(btn=>btn.addEventListener('click',()=>{state.stamps.splice(+btn.dataset.deleteStamp,1);viewStamps();refreshExport();drawOverlays()}));
 content.querySelectorAll('.stamp-card').forEach(card=>{
  const index=+card.dataset.stamp;card.querySelectorAll('[data-key]').forEach(inp=>{
   inp.addEventListener('change',()=>{const k=inp.dataset.key,s=state.stamps[index];if(!s)return;let val=inp.type==='checkbox'?inp.checked:inp.value;
    if(['image_index','size_mm','rotation'].includes(k))val=Number(val);
    if(k==='opacity')val=clamp(Number(val)/100,.05,1);
    if(k==='x'||k==='y')val=clamp(Number(val)/100,0,1);
    s[k]=val;
    if(k==='scope')card.querySelector('[data-custom]').hidden=val!=='custom';
    drawOverlays();
   });
  });
 });
}
function viewSeam(){
 $('seam-image').innerHTML=sealOptions(state.seam.image_index);$('seam-enabled').checked=state.seam.enabled;
 $('seam-side').value=state.seam.position;$('seam-size').value=state.seam.size_mm;$('seam-scope').value=state.seam.scope;$('seam-pages').value=state.seam.pages;$('seam-max').value=state.seam.max_pages;$('seam-pos').value=state.seam.position_percent;$('seam-opacity').value=Math.round(state.seam.opacity*100);$('seam-white').checked=state.seam.white_to_alpha;
 document.querySelectorAll('.seam-custom').forEach(el=>el.hidden=state.seam.scope!=='custom');
}
function pagesFor(scope,expr,count){if(scope==='all'||scope==='every')return Array.from({length:count},(_,i)=>i+1);if(scope==='first')return [1];if(scope==='last')return [count];if(scope==='odd')return Array.from({length:count},(_,i)=>i+1).filter(x=>x%2);if(scope==='even')return Array.from({length:count},(_,i)=>i+1).filter(x=>!(x%2));if(scope==='custom'){
  const p=new Set();for(const bit of String(expr).split(/[,，\s;；]+/)){if(/^\d+$/.test(bit))p.add(+bit);else if(/^\d+-\d+$/.test(bit)){const[a,b]=bit.split('-').map(Number);for(let j=a;j<=Math.min(b,count);j++)p.add(j)}}return [...p].filter(x=>x>=1&&x<=count).sort((a,b)=>a-b)}return []}
function groupsFor(pages,max){if(pages.length<2)return [];const count=Math.ceil(pages.length/max),base=Math.floor(pages.length/count),excess=pages.length%count;if(base===1)return [pages];let start=0;return Array.from({length:count},(_,i)=>{const n=base+(i<excess?1:0),g=pages.slice(start,start+n);start+=n;return g})}
async function imageElement(url){return new Promise((ok,bad)=>{const img=new Image();img.onload=()=>ok(img);img.onerror=bad;img.src=url})}
async function previewSeal(index,white,threshold=245){
 const key=`${index}/${white}/${threshold}`;if(state.sealCache.has(key))return state.sealCache.get(key);
 if(!state.seals[index])throw Error('缺少印章图片');
 if(!white)return state.originals[index];
 const img=await imageElement(state.originals[index]);const cnv=document.createElement('canvas');cnv.width=img.naturalWidth;cnv.height=img.naturalHeight;
 if(cnv.width*cnv.height>20e6)throw Error('印章图片尺寸过大');const ctx=cnv.getContext('2d',{willReadFrequently:true});ctx.drawImage(img,0,0);const pixels=ctx.getImageData(0,0,cnv.width,cnv.height);
 for(let i=0;i<pixels.data.length;i+=4){const m=Math.min(pixels.data[i],pixels.data[i+1],pixels.data[i+2]);if(m>=threshold)pixels.data[i+3]=0;else if(m>threshold-28)pixels.data[i+3]=Math.round(pixels.data[i+3]*(threshold-m)/28)}
 ctx.putImageData(pixels,0,0);const url=cnv.toDataURL('image/png');state.sealCache.set(key,url);return url;
}
async function drawOverlays(){
 const overlay=$('overlay'),info=currentInfo();if(!info||$('paper-wrap').hidden)return;
 const serial=++state.loadSerial;overlay.innerHTML='';const pg=info.sizes[state.page-1],pw=$('pdf-page').clientWidth,ph=$('pdf-page').clientHeight;if(!pw||!ph)return;
 const sx=pw/pg.width,sy=ph/pg.height;
 // Regular stamp layers. Each has a draggable handle directly on the stamp.
 for(let index=0;index<state.stamps.length;index++){
  const s=state.stamps[index];if(!pagesFor(s.scope,s.pages,info.pages).includes(state.page)||!state.seals[s.image_index])continue;
  try{const src=await previewSeal(s.image_index,s.white_to_alpha,s.threshold);const seal=await imageElement(src);if(serial!==state.loadSerial)return;
   const w=s.size_mm*mm2pt*sx,h=w*seal.naturalHeight/seal.naturalWidth;
   const el=document.createElement('img');el.src=src;el.className='overlay-stamp';el.draggable=false;el.title='拖动印章调整位置';
   Object.assign(el.style,{width:`${w}px`,height:`${h}px`,left:`${(pw-w)*s.x}px`,top:`${(ph-h)*s.y}px`,opacity:String(s.opacity),transform:`rotate(${s.rotation}deg)`});overlay.appendChild(el);
   el.addEventListener('pointerdown',e=>{e.preventDefault();el.setPointerCapture(e.pointerId);el.classList.add('dragging');const startX=e.clientX,startY=e.clientY,origX=s.x,origY=s.y;
    function move(ev){s.x=clamp(origX+(ev.clientX-startX)/Math.max(1,pw-w),0,1);s.y=clamp(origY+(ev.clientY-startY)/Math.max(1,ph-h),0,1);el.style.left=`${(pw-w)*s.x}px`;el.style.top=`${(ph-h)*s.y}px`}
    function finish(){el.removeEventListener('pointermove',move);el.classList.remove('dragging');viewStamps()}
    el.addEventListener('pointermove',move);el.addEventListener('pointerup',finish,{once:true});el.addEventListener('pointercancel',finish,{once:true});
   });
  }catch(err){notice('印章图片无法预览：'+err.message,true)}
 }
 // Seam layers: copy the exact selected segment of the seal image.
 const sm=state.seam;if(!sm.enabled||!state.seals[sm.image_index])return;
 const pages=pagesFor(sm.scope,sm.pages,info.pages);let group=null;for(const grp of groupsFor(pages,Number(sm.max_pages))){if(grp.includes(state.page)){group=grp;break}}if(!group)return;
 try{
  const src=await previewSeal(sm.image_index,sm.white_to_alpha,sm.threshold);const image=await imageElement(src);if(serial!==state.loadSerial)return;
  const idx=group.indexOf(state.page),n=group.length;const left=Math.round(idx*image.naturalWidth/n),right=Math.round((idx+1)*image.naturalWidth/n);
  const slice=document.createElement('canvas');slice.width=Math.max(1,right-left);slice.height=image.naturalHeight;const ctx=slice.getContext('2d');ctx.drawImage(image,left,0,right-left,image.naturalHeight,0,0,slice.width,slice.height);
  const wide=sm.position==='top'||sm.position==='bottom';let final=slice;
  if(wide){final=document.createElement('canvas');final.width=slice.height;final.height=slice.width;const fc=final.getContext('2d');fc.translate(0,final.height);fc.rotate(-Math.PI/2);fc.drawImage(slice,0,0)}
  const fsize=sm.size_mm*mm2pt*sx,sliceWidth=sm.size_mm*mm2pt*((right-left)/image.naturalWidth)*sx;
  const el=document.createElement('img');el.src=final.toDataURL('image/png');el.className='overlay-seam';el.style.opacity=String(sm.opacity);
  let x,y,w,h;if(!wide){w=sliceWidth;h=sm.size_mm*mm2pt*image.naturalHeight/image.naturalWidth*sy;x=sm.position==='right'?pw-w:0;y=(ph-h)*(1-sm.position_percent/100)}
  else{w=sm.size_mm*mm2pt*image.naturalHeight/image.naturalWidth*sx;h=sliceWidth*(sy/sx);x=(pw-w)*sm.position_percent/100;y=sm.position==='top'?0:ph-h}
  Object.assign(el.style,{left:`${x}px`,top:`${y}px`,width:`${w}px`,height:`${h}px`});overlay.appendChild(el);
 }catch(err){notice('骑缝章无法预览：'+err.message,true)}
}
async function renderPDF(){
 const serial=++state.loadSerial,info=currentInfo();viewFileSelect();$('overlay').innerHTML='';if(!info){$('empty-state').hidden=false;$('paper-wrap').hidden=true;$('preview-loading').hidden=true;return}
 $('empty-state').hidden=true;$('paper-wrap').hidden=true;$('preview-loading').hidden=false;
 const form=new FormData();form.append('file',state.pdfs[state.active]);form.append('page',String(state.page));form.append('password',$('input-password').value);
 try{const r=await fetch('/api/render',{method:'POST',body:form});if(!r.ok){const j=await r.json().catch(()=>({detail:'PDF 预览失败'}));throw Error(j.detail)}const blob=await r.blob();if(serial!==state.loadSerial)return;
  const url=URL.createObjectURL(blob),img=$('pdf-page');if(state.sourceUrl)URL.revokeObjectURL(state.sourceUrl);state.sourceUrl=url;
  await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject;img.src=url});if(serial!==state.loadSerial)return;
  const stage=$('preview-stage');const fitted=Math.min(720,Math.max(300,stage.clientWidth-56),img.naturalWidth);$('paper-wrap').style.width=`${fitted}px`;
  $('paper-wrap').hidden=false;$('preview-loading').hidden=true;drawOverlays();
 }catch(err){if(serial!==state.loadSerial)return;$('preview-loading').hidden=true;$('empty-state').hidden=false;notice(`预览失败：${err.message}`,true)}
}
function getConfig(){return {stamps:state.stamps.map(s=>({...s})),seam:{...state.seam},input_password:$('input-password').value,output_password:$('output-password').value,allow_signature_invalidation:$('allow-signed').checked}}
async function exportPDF(){if(!validDownload())return;const button=$('export');button.disabled=true;button.textContent='正在盖章并生成文件…';
 try{const fd=new FormData();state.pdfs.forEach(f=>fd.append('pdfs',f));state.seals.forEach(f=>fd.append('seals',f));fd.append('settings',JSON.stringify(getConfig()));const response=await fetch('/api/export',{method:'POST',body:fd});if(!response.ok){const j=await response.json().catch(()=>({detail:'处理失败'}));throw Error(j.detail)}
  const data=await response.blob();const content=response.headers.get('Content-Disposition')||'';let filename=state.pdfs.length>1?'批量已盖章.zip':'已盖章.pdf';const m=content.match(/filename\*=UTF-8''([^;]+)/);if(m){try{filename=decodeURIComponent(m[1])}catch(_){}}
  const url=URL.createObjectURL(data),a=document.createElement('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);notice(`盖章成功：${state.pdfs.length} 份 PDF 已生成。`);
 }catch(err){notice(err.message||'PDF 盖章失败',true)}finally{button.textContent='导出已盖章 PDF ↗';refreshExport()}
}
function initialize(){
 $('pdf-files').addEventListener('change',e=>addPDFs(e.target.files));$('seal-files').addEventListener('change',e=>addSeals(e.target.files));
 for(const evt of ['dragenter','dragover'])$('pdf-drop').addEventListener(evt,e=>{e.preventDefault();$('pdf-drop').classList.add('drag')});
 for(const evt of ['dragleave','drop'])$('pdf-drop').addEventListener(evt,e=>{e.preventDefault();$('pdf-drop').classList.remove('drag')});
 $('pdf-drop').addEventListener('drop',e=>addPDFs(e.dataTransfer.files));
 $('preview-file').addEventListener('change',e=>{state.active=Number(e.target.value);state.page=1;viewPDFList();renderPDF()});
 $('prev-page').addEventListener('click',()=>{state.page=Math.max(1,state.page-1);renderPDF()});$('next-page').addEventListener('click',()=>{state.page=Math.min(currentInfo().pages,state.page+1);renderPDF()});
 $('tab-normal').addEventListener('click',()=>{ $('tab-normal').classList.add('active');$('tab-seam').classList.remove('active');$('normal-pane').hidden=false;$('seam-pane').hidden=true});
 $('tab-seam').addEventListener('click',()=>{ $('tab-seam').classList.add('active');$('tab-normal').classList.remove('active');$('normal-pane').hidden=true;$('seam-pane').hidden=false});
 $('add-stamp').addEventListener('click',()=>{if(!state.seals.length){notice('请先添加印章图片。',true);return}if(state.stamps.length>=12){notice('最多 12 个普通章。',true);return}state.stamps.push(defaultStamp());viewStamps();refreshExport();drawOverlays()});
 const mapping=[['seam-enabled','enabled','checkbox'],['seam-image','image_index','number'],['seam-side','position','string'],['seam-size','size_mm','number'],['seam-scope','scope','string'],['seam-pages','pages','string'],['seam-max','max_pages','number'],['seam-pos','position_percent','number'],['seam-opacity','opacity','percent'],['seam-white','white_to_alpha','checkbox']];
 mapping.forEach(([id,key,type])=>$(id).addEventListener('change',e=>{let val=type==='checkbox'?e.target.checked:e.target.value;if(type==='number')val=Number(val);if(type==='percent')val=Number(val)/100;state.seam[key]=val;if(key==='scope')document.querySelectorAll('.seam-custom').forEach(el=>el.hidden=val!=='custom');refreshExport();drawOverlays()}));
 $('export').addEventListener('click',exportPDF);$('reset').addEventListener('click',()=>{if(!confirm('重置盖章设置？已选择的 PDF 和印章素材将保留。'))return;state.stamps=state.seals.length?[defaultStamp()]:[];state.seam={enabled:false,image_index:0,position:'right',size_mm:40,scope:'all',pages:'',max_pages:12,position_percent:50,opacity:.95,white_to_alpha:true,threshold:245};$('output-password').value='';$('allow-signed').checked=false;viewSeam();viewStamps();refreshExport();drawOverlays()});
 $('help-open').addEventListener('click',e=>{e.preventDefault();$('help').showModal()});$('help-close').addEventListener('click',()=>$('help').close());
 $('input-password').addEventListener('change',async()=>{if(!state.pdfs.length)return;try{state.infos=await Promise.all(state.pdfs.map(f=>inspectFile(f)));viewPDFList();renderPDF()}catch(err){notice('原 PDF 密码不正确或无法读取：'+err.message,true)}});
 window.addEventListener('resize',()=>{if(!currentInfo()||$('paper-wrap').hidden)return;const stage=$('preview-stage'),image=$('pdf-page');const fitted=Math.min(720,Math.max(280,stage.clientWidth-56),image.naturalWidth);$('paper-wrap').style.width=`${fitted}px`;drawOverlays()});
 viewSeam();viewStamps();viewSeals();viewPDFList();viewFileSelect();refreshExport();
}
window.addEventListener('DOMContentLoaded',initialize);
