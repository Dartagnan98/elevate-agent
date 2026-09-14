import { useEffect, useRef, useState } from "react";
import WizardSurface from "./wizard-surface";
import { kitRequest } from "./kit-save-queue";
import "./kit-pdf-editor.css";

export type PdfField = {name:string;label:string;type:"text"|"choice"|"select";value:string;on:string;radio:boolean;options:string[];multiline:boolean;maxLength:number;rect:number[]};
export type PdfPage = {width:number;height:number;fields:PdfField[]};
type PdfState = {revision:string;pages:PdfPage[];stale:boolean;signed:boolean;edited:boolean};

export function pdfInitialValues(pages:PdfPage[]) {
  const initial:Record<string,string>={};
  for(const p of pages)for(const f of p.fields) {
    // Unchecked widgets in a shared checkbox/radio group must not erase its selection.
    if(f.type!=="choice"||!(f.name in initial)||f.value)initial[f.name]=f.value;
  }
  return initial;
}

export function changedPdfFields(original:Record<string,string>, current:Record<string,string>) {
  return Object.fromEntries(Object.entries(current).filter(([key,value])=>value !== original[key]));
}

export default function KitPdfEditor({url, name, onClose, onSaved}: {url:string;name:string;onClose:()=>void;onSaved:()=>void}) {
  const [pdf,setPdf]=useState<PdfState|null>(null);
  const [values,setValues]=useState<Record<string,string>>({});
  const original=useRef<Record<string,string>>({});
  const current=useRef(values);current.current=values;
  const [previewOnly,setPreviewOnly]=useState(false);
  const [page,setPage]=useState(0), [zoom,setZoom]=useState("fit");
  const [image,setImage]=useState(""), [imageError,setImageError]=useState("");
  const [error,setError]=useState(""), [message,setMessage]=useState("");
  const [saving,setSaving]=useState(false), [active,setActive]=useState<PdfField|null>(null);
  const savePending=useRef<Promise<void>|null>(null);
  const [loadKey,setLoadKey]=useState(0);
  const changed=changedPdfFields(original.current,values), dirty=Object.keys(changed).length>0;
  const readonly=!!pdf?.stale||!!pdf?.signed;
  useEffect(()=>{
    let alive=true;
    setError("");
    kitRequest(url).then(r=>r.json()).then((body:PdfState)=>{
      if(!alive)return;
      const initial=pdfInitialValues(body.pages);
      original.current=initial;current.current=initial;setValues(initial);setPdf(body);setPage(Math.max(0,body.pages.findIndex(p=>p.fields.length>0)));
    }).catch(e=>{if(alive)setError(String(e.message||e));});
    return()=>{alive=false;};
  },[url,loadKey]);
  useEffect(()=>{
    if(!pdf)return;
    let alive=true, blobUrl="";setImage("");setImageError("");
    kitRequest(`${url}/page/${page+1}?revision_id=${encodeURIComponent(pdf.revision)}`).then(r=>r.blob()).then(blob=>{
      if(!alive)return;blobUrl=URL.createObjectURL(blob);setImage(blobUrl);
    }).catch(e=>{if(alive)setImageError(String(e.message||e));});
    return()=>{alive=false;if(blobUrl)URL.revokeObjectURL(blobUrl);};
  },[url,pdf?.revision,page]);
  useEffect(()=>{
    const guard=(e:BeforeUnloadEvent)=>{if(Object.keys(changedPdfFields(original.current,current.current)).length){e.preventDefault();e.returnValue="";}};
    window.addEventListener("beforeunload",guard);return()=>window.removeEventListener("beforeunload",guard);
  },[]);
  const update=(key:string,value:string)=>{
    const next={...current.current,[key]:value};current.current=next;setValues(next);setMessage("");
  };
  const save=():Promise<void>=>{
    if(savePending.current)return savePending.current;
    const edits=changedPdfFields(original.current,current.current);
    if(!pdf||!Object.keys(edits).length)return Promise.resolve();
    setSaving(true);setError("");
    const snapshot={...current.current};
    const pending=kitRequest(url,{method:"PUT",body:JSON.stringify({revision:pdf.revision,values:edits})})
      .then(r=>r.json()).then(body=>{
        const savedPages:PdfPage[]|undefined=body.pdf?.pages;
        const savedValues=savedPages?pdfInitialValues(savedPages):snapshot;
        original.current=savedValues;current.current=savedValues;setValues(savedValues);
        setPdf(p=>p?{...p,...(body.pdf||{}),revision:body.revision,edited:true}:p);
        if(savedPages){setPage(p=>Math.min(p,savedPages.length-1));setActive(null);}
        setMessage("Saved to this document. Your edits will be kept if it is redrafted.");onSaved();
      }).catch(e=>{setError(String(e.message||e));throw e;})
      .finally(()=>{setSaving(false);savePending.current=null;});
    savePending.current=pending;return pending;
  };
  const currentPage=pdf?.pages[page];
  const fieldControl=(f:PdfField, onPage=false)=>{
    const common={"aria-label":f.label,disabled:saving||readonly,value:values[f.name]??"",onChange:(e:React.ChangeEvent<HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement>)=>update(f.name,e.target.value)};
    if(f.type==="choice")return <input aria-label={f.label} type="checkbox" disabled={saving||readonly} checked={values[f.name]===f.on} onFocus={()=>setActive(f)} onChange={e=>update(f.name,e.target.checked?f.on:"")}/>;
    if(f.type==="select")return <select {...common} onFocus={()=>setActive(f)}><option value=""/>{f.options.map(o=><option key={o}>{o}</option>)}</select>;
    return f.multiline ? <textarea {...common} rows={onPage?undefined:3} maxLength={f.maxLength||undefined} onFocus={()=>setActive(f)} spellCheck/>
      : <input {...common} maxLength={f.maxLength||undefined} onFocus={()=>setActive(f)} type="text"/>;
  };
  return <WizardSurface title={name} subtitle="Edit & review PDF" label={`Edit ${name}`} closeLabel="← Back to documents" className="kit-pdf-workspace" beforeClose={save} onClose={onClose}>
    <div className="kit-pdf-toolbar">
      <div className="kit-pdf-pages">
        <button type="button" className="kit-secondary" disabled={!pdf||page===0} onClick={()=>{setPage(p=>p-1);setActive(null);}} aria-label="Previous page">←</button>
        <label>Page <select aria-label="Page" value={page} onChange={e=>{setPage(Number(e.target.value));setActive(null);}}>{pdf?.pages.map((_,i)=><option key={i} value={i}>{i+1} of {pdf.pages.length}</option>)}</select></label>
        <button type="button" className="kit-secondary" disabled={!pdf||page===pdf.pages.length-1} onClick={()=>{setPage(p=>p+1);setActive(null);}} aria-label="Next page">→</button>
      </div>
      <label>Zoom <select aria-label="Zoom" value={zoom} onChange={e=>setZoom(e.target.value)}><option value="fit">Fit width</option><option value="1.25">125%</option><option value="1.5">150%</option><option value="2">200%</option></select></label>
      <button type="button" className="kit-primary" disabled={!dirty||saving||readonly} onClick={()=>void save().catch(()=>{})}>{saving?"Saving…":"Save changes"}</button>
      <button type="button" className="kit-secondary" disabled={!pdf||saving} onClick={()=>{if(previewOnly)setPreviewOnly(false);else void save().then(()=>{setPreviewOnly(true);setActive(null);}).catch(()=>{});}}>{previewOnly?"Edit fields":"Review saved PDF"}</button>
      <span role="status">{saving?"Saving your PDF…":dirty?`${Object.keys(changed).length} unsaved ${Object.keys(changed).length===1?"field":"fields"}`:message||(pdf?"All changes saved":"Opening…")}</span>
    </div>
    {error&&<div role="alert" className="kit-pdf-error">{error}{!pdf&&<button className="kit-secondary" onClick={()=>setLoadKey(k=>k+1)}>Try again</button>}{dirty&&<button className="kit-secondary" disabled={saving} onClick={onClose}>Discard unsaved changes and close</button>}</div>}
    {!pdf&&!error&&<p role="status">Opening the PDF…</p>}
    {pdf?.stale&&<p className="kit-pdf-error">Property or document details have changed. Close this view and redraft once to bring them into the PDF. Your saved PDF edits will be preserved.</p>}
    {pdf?.signed&&<p>This PDF is signed and is available for review only.</p>}
    {pdf&&!readonly&&<p className="kit-pdf-help">{previewOnly ? "This is the saved PDF. Choose Edit fields to make another change." : "Click a highlighted field on the page to edit it. Changes apply to this document and also save when you return to Documents."}</p>}
    {currentPage&&!readonly&&!previewOnly&&<label className="kit-pdf-field-picker">Edit a field <select aria-label="Choose a field on this page" value={active?String(currentPage.fields.indexOf(active)):""} onChange={e=>setActive(currentPage.fields[Number(e.target.value)]||null)}><option value="">Choose a field…</option>{currentPage.fields.map((f,i)=><option key={i} value={i}>{f.label}</option>)}</select></label>}
    {active&&!readonly&&!previewOnly&&<div className="kit-pdf-active"><label>{active.label}</label>{fieldControl(active)}<small>Editing this field on the PDF. The larger control makes small fields easier to fill.</small></div>}
    {imageError&&<p role="alert" className="kit-pdf-error">{imageError}</p>}
    {pdf&&!image&&!imageError&&<p role="status">Loading page {page+1}…</p>}
    {image&&currentPage&&<div className="kit-pdf-canvas-scroll"><div className="kit-pdf-page" style={{width:zoom==="fit"?"100%":currentPage.width*Number(zoom),aspectRatio:`${currentPage.width}/${currentPage.height}`}}>
      <img src={image} alt={`Page ${page+1} of ${name}`} draggable={false}/>
      {!readonly&&!previewOnly&&currentPage.fields.map((f,i)=><div key={`${page}:${i}`} title={f.label} className={`kit-pdf-field ${f.type} ${active?.name===f.name?"active":""}`} style={{left:`${f.rect[0]/currentPage.width*100}%`,top:`${f.rect[1]/currentPage.height*100}%`,width:`${f.rect[2]/currentPage.width*100}%`,height:`${f.rect[3]/currentPage.height*100}%`}}>{fieldControl(f,true)}</div>)}
    </div></div>}
    {currentPage&&!readonly&&!currentPage.fields.length&&<p>This page has no fillable fields. Use the page selector to continue reviewing.</p>}
  </WizardSurface>;
}
