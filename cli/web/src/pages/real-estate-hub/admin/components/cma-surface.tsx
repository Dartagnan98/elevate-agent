// The CMA as a full surface — mockup screens 1-11 all sit on one.
//
// The wizard used to be a collapsible panel inside the deal card, competing for
// the same scroll with Listing Kit, approvals and documents. The mockup gives a
// market evaluation its own screen with one job, which is most of why the built
// thing "didn't look like the mockups" even where the content matched.
//
// Rendered as a layer ABOVE the deal card rather than a route, so closing it
// reveals the card still sitting underneath, which is where Skyleigh asked to
// land. Nothing to navigate back to and no state to restore.
import { useEffect, useState } from "react";
import CmaWizard from "./cma-wizard";
import WizardSurface from "./wizard-surface";

export default function CmaSurface({ dealId, address, area, sellerName, onClose }: {
  dealId:string;address?:string|null;area?:string|null;sellerName?:string|null;onClose:()=>void;
}) {
  const [shownAddr,setShownAddr] = useState(address || "");
  useEffect(()=>setShownAddr(address || ""),[address]);
  return <WizardSurface title={shownAddr || "Market evaluation"} subtitle={[area, sellerName, "CMA"].filter(Boolean).join(" · ")} label={`Market evaluation${shownAddr ? ` for ${shownAddr}` : ""}`} onClose={onClose}>
    <CmaWizard dealId={dealId} bare address={shownAddr} onAddressChange={setShownAddr}/>
  </WizardSurface>;
}
