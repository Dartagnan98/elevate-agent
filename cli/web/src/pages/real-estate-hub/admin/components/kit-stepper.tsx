/** The CMA numbered progress rail, with keyboard-accessible steps. */
export default function KitStepper({steps, current, complete, onSelect, mobile}: {
  steps: readonly string[]; current: number; complete: (step:number)=>boolean;
  onSelect:(step:number)=>void; mobile:boolean;
}) {
  return <nav aria-label="Document preparation progress" style={{display:'flex',alignItems:'center',marginBottom:18}}>
    {steps.map((label,i)=>{
      const n=i+1, done=complete(n), active=current===n;
      return <div key={label} style={{display:'flex',alignItems:'center',flex:i<steps.length-1?1:'0 0 auto',minWidth:0}}>
        <button type="button" onClick={()=>onSelect(n)} aria-current={active?'step':undefined} aria-label={`${label}${done?', complete':''}`} title={label}
          style={{display:'flex',alignItems:'center',border:0,background:'transparent',padding:0,minHeight:44,cursor:'pointer',font:'inherit'}}>
          <span aria-hidden="true" style={{width:28,height:28,borderRadius:'50%',flexShrink:0,display:'flex',alignItems:'center',justifyContent:'center',fontSize:12.5,fontWeight:700,
            background:done?'var(--ds-done)':active?'var(--ds-terracotta)':'#e7ebf2',color:done||active?'#fff':'var(--ds-muted)',
            boxShadow:active?`0 0 0 ${done?3:4}px ${done?'#d6eade':'#f5dccf'}`:undefined}}>{done?'✓':n}</span>
          {(!mobile||active)&&<span style={{fontSize:11.5,fontWeight:active?700:600,marginLeft:7,whiteSpace:'nowrap',color:done?'var(--ds-done)':'var(--ds-ink)'}}>{label}</span>}
        </button>
        {i<steps.length-1&&<span aria-hidden="true" style={{flex:1,height:3,background:done?'var(--ds-done)':'#e7ebf2',margin:mobile?'0 4px':'0 8px',borderRadius:2}}/>}
      </div>;
    })}
  </nav>;
}
