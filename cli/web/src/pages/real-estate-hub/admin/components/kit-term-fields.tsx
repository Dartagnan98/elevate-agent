import { useCallback, useEffect, useId, useRef, useState } from "react";
import { kitRequest } from "./kit-save-queue";
import "./kit-workspace.css";

export const PREFERENCE_FIELDS = [
  ["cpsDepositTerms", "Deposit due"], ["cpsDepositHolder", "Deposit held by"],
  ["designatedAgency", "Designated agent"], ["designatedAgency2", "Second designated agent (optional)"], ["listingCommission", "Listing commission"],
  ["buyerAgencyComp", "Buyer agency compensation"],
] as const;
const DATE_KEYS = new Set(["subjectRemovalDate", "completionDate", "possessionDate", "adjustmentDate", "listingDate", "expiryDate", "offerDate", "viewedDate", "offerOpenDate"]);
export function dateValue(value: string): string {
  // Never guess the year of an older shorthand date.
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/.exec(value);
  if (!match) return "";
  const date = new Date(`${match[1]}-${match[2]}-${match[3]}T12:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0,10) === value.slice(0,10) ? value.slice(0,10) : "";
}
export const INCLUDED_ITEMS = ["Refrigerator", "Stove", "Dishwasher", "Washer", "Dryer", "Microwave", "Window coverings", "Blinds", "Light fixtures", "Garage door opener and remotes", "Air conditioning", "Central vacuum and attachments"];
export function toggleIncluded(value: string, item: string, checked: boolean): string {
  const parts = value.split(/;|\n/).map(x=>x.trim()).filter(Boolean);
  const next = parts.filter(x=>x.toLowerCase() !== item.toLowerCase());
  if (checked) next.push(item);
  return next.join("; ");
}
export function TermField({ label, field, value = "", placeholder = "", save, preference }: {
  label: string; field: string; value?: string; placeholder?: string;
  save: (field:string,value:string)=>void; preference?: string;
}) {
  const id = useId(); const [draft,setDraft] = useState(value); const focused = useRef(false);
  useEffect(()=>{ if (!focused.current) setDraft(value); },[value]);
  const isDate = DATE_KEYS.has(field), included = field === "cpsInclusions";
  const update = (next:string) => { setDraft(next); save(field,next); };
  const inputProps = {id, onFocus:()=>{focused.current=true;}, onBlur:()=>{focused.current=false; if (!isDate && draft !== value) save(field,draft);}};
  return <div className={`kit-term${included ? " kit-items" : ""}`}>
    <label htmlFor={id}>{label}</label>
    {included || field === "cpsExclusions" ? <textarea {...inputProps} value={draft} placeholder={placeholder} onChange={e=>setDraft(e.target.value)}/>
      : <input {...inputProps} type={isDate ? "date" : ["possessionTime", "offerOpenTime"].includes(field) ? "time" : "text"} value={isDate ? dateValue(draft) : draft} placeholder={isDate ? undefined : placeholder} onChange={e=>isDate ? update(e.target.value) : setDraft(e.target.value)}/>}
    {isDate && draft && !dateValue(draft) && <small>Saved date: {draft}. Choose a calendar date to replace it; the saved text is kept until then.</small>}
    {preference && preference !== draft && <button type="button" className="kit-use-default" onClick={()=>update(preference)}>Use saved preference: {preference}</button>}
    {included && <details><summary>Choose included items</summary><div className="kit-items-options">{INCLUDED_ITEMS.map(item=><label key={item}><input type="checkbox" checked={draft.split(/;|\n/).some(x=>x.trim().toLowerCase()===item.toLowerCase())} onChange={e=>update(toggleIncluded(draft,item,e.target.checked))}/>{item}</label>)}</div><small>Add or edit any wording in the field above. Separate items with a semicolon.</small></details>}
  </div>;
}

export function useKitPreferences(dealId:string, side:"buyer"|"listing", extra:Record<string,any>, save:(key:string,value:any)=>Promise<unknown>) {
  const [preferences,setPreferences] = useState<Record<string,string>>({});
  const [error,setError] = useState("");
  const ready = useRef<Promise<unknown>>(Promise.resolve());
  const latest = useRef({extra,save}); latest.current={extra,save};
  useEffect(()=>{
    let alive=true;
    ready.current = kitRequest('/api/admin/kit-preferences').then(r=>r.json()).then(async body=>{
      if (!alive) return;
      setPreferences(body.values || {});
      for (const [key] of PREFERENCE_FIELDS) {
        if (!alive) return;
        if (side === 'listing' && key.startsWith('cps')) continue;
        if (side === 'buyer' && ['listingCommission','buyerAgencyComp'].includes(key)) continue;
        // Explicit null/empty fields are deliberate clears, not missing data.
        if (!Object.prototype.hasOwnProperty.call(latest.current.extra,key) && body.values?.[key]) await latest.current.save(key,body.values[key]);
      }
    }).catch(e=>{if(alive)setError(`Could not load or apply preferences: ${String(e)}`);});
    return ()=>{alive=false;};
  },[dealId,side]);
  const waitForPreferences = useCallback(async()=>{await ready.current;},[]);
  return {preferences,setPreferences,preferenceError:error,waitForPreferences};
}

export function KitPreferences({ side, values, onSaved, onApply }: {side:"buyer"|"listing";values:Record<string,string>;onSaved:(v:Record<string,string>)=>void;onApply?:(v:Record<string,string>)=>Promise<void>}) {
  const [applyCurrent,setApplyCurrent] = useState(true);
  const [draft,setDraft] = useState(values); const [busy,setBusy]=useState(false); const [message,setMessage]=useState("");
  useEffect(()=>setDraft(values),[values]);
  const save = async()=>{
    setBusy(true);setMessage("");
    try { const r=await kitRequest('/api/admin/kit-preferences',{method:'PUT',body:JSON.stringify({values:draft})}); const body=await r.json();onSaved(body.values);if(applyCurrent&&onApply)await onApply(body.values);setMessage(applyCurrent&&onApply?'Preferences saved and applied to this transaction. Redraft existing documents to update them.':'Preferences saved for future transactions.'); }
    catch(e){setMessage(`Could not finish saving or applying preferences: ${String(e)}`);}finally{setBusy(false);}
  };
  return <details className="kit-preferences"><summary>Saved preferences</summary>
    <p>Set the terms you usually use. They fill missing fields when you open a kit. You can change any value for one transaction.</p>
    <div className="kit-preferences-grid">{PREFERENCE_FIELDS.filter(([key])=>side === "buyer" ? !["listingCommission","buyerAgencyComp"].includes(key) : !key.startsWith("cps")).map(([key,label])=><TermField key={key} field={key} label={label} value={draft[key] || ''} save={(k,v)=>setDraft(p=>({...p,[k]:v}))}/>)}</div>
    {onApply&&<label><input type="checkbox" checked={applyCurrent} onChange={e=>setApplyCurrent(e.target.checked)}/> Also apply these preferences to this transaction</label>}
    <button className="kit-primary" type="button" disabled={busy} onClick={()=>void save()}>{busy?'Saving…':'Save preferences'}</button>
    {message && <p role="status">{message}</p>}
  </details>;
}
