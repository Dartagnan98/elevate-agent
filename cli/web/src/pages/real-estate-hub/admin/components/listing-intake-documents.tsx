import WaitingCard, { openListingKitPdf, type WaitingRunLike } from "./waiting-card";

type Document = { id: string; name?: string; filePath?: string; ready?: boolean; editedAt?: string; generatedAt?: string };
type Run = { id: string; status: string; humanPrompt?: Record<string, unknown> | null; skill?: string | null; registryName?: string | null };

export default function ListingIntakeDocuments({dealId, extra, runs, onOpen, onResolved}: {
  dealId: string; extra: Record<string, any>; runs: Run[]; onOpen: () => void; onResolved: () => void;
}) {
  const forms = extra.listingKitForms || {};
  const docs: Document[] = (extra.listingKit?.documents || []).filter((d: Document) => d.id === "mlc" || forms[d.id] !== false);
  const waiting = runs.filter(r => r.status === "waiting_human" &&
    (r.humanPrompt?.titleOrder || r.humanPrompt?.titleVerification || (r.humanPrompt?.documentReview as {kit?: string} | undefined)?.kit === "listing" || r.humanPrompt?.title === "Listing drafts need preparation"));
  return <section aria-label="Listing Intake documents" className="abm-intake-documents">
    <div className="abm-section-label mono">DOCUMENTS · LISTING INTAKE</div>
    <p>{extra.listingTitleVerification?.status === "verified" && extra.listingTitleVerification?.ownerMatch === true ? "Current title saved; sellers reconciled against title." : "The MLC cannot be approved until the current title verifies every seller’s full legal name."}
      {extra.listingTitleVerification?.filePath && <button type="button" className="abm-waiting-btn preview" onClick={() => openListingKitPdf(dealId, "title")}>Open title ↗</button>}
      {extra.listingTitleVerification?.driveWebViewLink && <a className="abm-waiting-btn preview" href={String(extra.listingTitleVerification.driveWebViewLink)} target="_blank" rel="noreferrer">Open filed title in Drive ↗</a>}
    </p>
    {waiting.filter(r => r.humanPrompt?.titleOrder || r.humanPrompt?.titleVerification).map(r => <WaitingCard key={r.id} run={{runId:r.id, dealId, humanPrompt:r.humanPrompt || {}}} onResolved={onResolved}/>)}
    {!docs.length && <p>Listing drafts will appear here when prepared from your intake.</p>}
    <ul className="abm-checklist">
      {docs.map(doc => {
        const stale = !!doc.editedAt && (!doc.generatedAt || doc.editedAt > doc.generatedAt);
        const ready = !!doc.filePath && doc.ready !== false;
        return <li key={doc.id} className="abm-intake-document-row">
          <span>{doc.name || doc.id.toUpperCase()}<small>{stale ? "Needs redraft" : ready ? "Draft for review" : "Not prepared yet"}</small></span>
          {ready && <button type="button" className="abm-waiting-btn preview" onClick={() => openListingKitPdf(dealId, doc.id)}>Open {doc.id.toUpperCase()} ↗</button>}
        </li>;
      })}
    </ul>
    <button type="button" className="abm-waiting-btn preview" onClick={onOpen}>Review / edit listing documents →</button>
    {waiting.filter(r => !r.humanPrompt?.titleOrder && !r.humanPrompt?.titleVerification).map(r => <WaitingCard key={r.id} run={{runId:r.id, dealId, humanPrompt:r.humanPrompt || {}, skill:r.skill, registryName:r.registryName} as WaitingRunLike} onResolved={onResolved}/>)}
  </section>;
}
