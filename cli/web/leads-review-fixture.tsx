import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import LeadsTable from "./src/pages/real-estate-hub/leads/components/leads-table";
import type { LeadsDraft, LeadsProfile } from "./src/pages/real-estate-hub/leads/leads-data";
import "./src/elevate-design-system.css";
import "./src/pages/real-estate-hub/leads/leads.css";
const names=["Alex Morgan","Jordan Chen","Casey Williams"];
const profiles=Array.from({length:55},(_,i)=>({id:`p${i}`,name:names[i]||`Contact ${i}`,contactIds:[`c${i}`],heat:.5,group:"verified",verified:true,status:"prospect",source:"Lofty CRM",email:`person${i}@example.test`,phone:"+1 250 555 0100",contact:"",threads:1,age:"1d",tags:[],sub:"",lastMsg:"",lastTouch:"Yesterday",temperature:"warm"} as LeadsProfile));
const seed=names.map((name,i)=>({id:`d${i}`,name,source:"Lofty CRM",sourceId:"crm",taskId:`t${i}`,contactId:`c${i}`,channel:"SMS",age:"1h",body:`Hi ${name.split(" ")[0]} :)\n\nYou mentioned looking for a home with more room. Are you still exploring the same area, or have your plans changed?`,heat:"warm"} as LeadsDraft));
window.__fixtureCalls=[];
function Fixture(){const [drafts,setDrafts]=useState(seed);window.__changeFixture=()=>setDrafts(ds=>ds.map(d=>d.id==="d0"?{...d,body:"Updated by another session"}:d));return <main className="app leads-design-embedded" style={{padding:20,maxWidth:1500,margin:"0 auto"}}><LeadsTable profiles={profiles} drafts={drafts} kpis={{drafts:drafts.length,hot:0,avgFirstTouch:"—",replyRate:"—",newLeads7d:3}} onOpen={()=>{window.__opened=true;}} onDraftAction={async(action,d)=>{window.__fixtureCalls.push({action,id:d.id,body:d.body});await new Promise(r=>setTimeout(r,100));if(new URLSearchParams(location.search).has("fail")&&d.id==="d1")throw new Error("Simulated connection loss");setDrafts(ds=>ds.filter(x=>x.id!==d.id));}} /></main>}
createRoot(document.getElementById("root")!).render(<Fixture/>);
