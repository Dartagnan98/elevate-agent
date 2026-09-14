import { useCallback, useRef } from "react";
import WizardSurface from "./wizard-surface";
import OfferKitWizard from "./offer-kit-wizard";
import ListingKitWizard from "./listing-kit-wizard";

export default function KitSurface({side,dealId,extra,address,dealTitle,currentStage,onUpdate,onClose,initialStep}: {
  side:"buyer"|"listing";dealId:string;extra:Record<string,any>;address?:string;dealTitle?:string;currentStage?:number;onUpdate:()=>void;onClose:()=>void;initialStep?:number;
}) {
  const flush = useRef<()=>Promise<void>>(async()=>{});
  const onSaveReady = useCallback((save:()=>Promise<void>)=>{flush.current=save;},[]);
  const shared={dealId,extra,address,dealTitle,currentStage,onUpdate,onSaveReady,bare:true};
  const label=side==='buyer'?'Transaction Kit':'Listing Kit';
  return <WizardSurface title={address || dealTitle || label} subtitle={`${label} · Document preparation`} label={label} onClose={onClose} beforeClose={()=>flush.current()}>
    {side==='buyer'?<OfferKitWizard {...shared} buyerName={extra.buyerNames}/>:<ListingKitWizard {...shared} sellerName={extra.sellerNames} initialStep={initialStep}/>}
  </WizardSurface>;
}
