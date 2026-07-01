// Documents panel for a deal card — a window into the deal's Google Drive folder.
// Files stay in Drive (backed up + shareable); this just lists/links them,
// grouped by type. Drop into:
//   cli/web/src/pages/real-estate-hub/admin/components/documents-panel.tsx
// then render from deal-modal.tsx where the card sections live:
//   <DocumentsPanel dealId={deal.id} address={(contextDeal as any)?.listingAddress} />
//
// WIRE-IN (do these with the all-clear, one session deploying):
//  1. api.ts:  listDealDocuments(dealId) -> GET /api/admin/deals/{id}/documents
//  2. admin_deals.py:  @router.get("/api/admin/deals/{deal_id}/documents")
//       -> spawn ~/skyleigh-tools/scripts/deal-docs-list.py --address <listingAddress>
//       (same /usr/bin/python3 + user-site env pattern as the offer-prep routes;
//        legal/PID address from the deal record)
//  3. deal-modal.tsx:  add this section to every card (after the header sections).
import { useEffect, useState } from "react";
import { api } from "../../../../lib/api";

const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef", BLUE = "#5E8AD0", GREEN = "#2f7a4d", TERRA = "#C46340";

type DocFile = { name: string; id: string; url: string; mime: string; modified: string; group: string; tag: string };
const GROUP_ORDER = ["Property & Title", "Offer Kit", "Documents"];
const GROUP_NOTE: Record<string, string> = {
  "Property & Title": "pulled when you prep the package",
  "Offer Kit": "generated from this card",
  "Documents": "",
};
const TAG_COLOR: Record<string, [string, string]> = {
  Latest: ["#eaf5ee", GREEN], Title: ["#eef4fc", "#2c4a78"], MLS: ["#eef4fc", "#2c4a78"],
  Zoning: ["#eef4fc", "#2c4a78"], Assessment: ["#eef4fc", "#2c4a78"], PDS: ["#eef4fc", "#2c4a78"],
  Strata: ["#eef4fc", "#2c4a78"], FINTRAC: ["#fdf1e9", TERRA], Added: ["#fdf1e9", TERRA],
};

export default function DocumentsPanel({ dealId, missing }: { dealId: string; address?: string; missing?: string[] }) {
  const [files, setFiles] = useState<DocFile[]>([]);
  const [folderUrl, setFolderUrl] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.listDealDocuments(dealId)
      .then((r) => { if (live) { setFiles(r.files || []); setFolderUrl(r.folderUrl || ""); } })
      .catch(() => { if (live) setFiles([]); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [dealId]);

  const isImg = (m: string) => /image\//.test(m);
  const isFolder = (m: string) => /\.folder$/.test(m);
  // Every file gets a bucket so the card is a full mirror of the Drive folder:
  // known groups first (in order), then any other group Drive reports, then a
  // catch-all for files with no group. Nothing in the folder is ever hidden.
  const grp = (f: DocFile) => (f.group && f.group.trim() ? f.group : "Documents");
  const extraGroups = Array.from(new Set(files.map(grp))).filter((g) => !GROUP_ORDER.includes(g));
  const groups = [...GROUP_ORDER, ...extraGroups].filter((g) => files.some((f) => grp(f) === g));

  return (
    <section style={{ border: `1px solid ${LINE}`, borderRadius: 12, marginTop: 14, overflow: "hidden", background: "#fff" }}>
      <header onClick={() => setOpen((o) => !o)}
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", padding: "13px 16px", background: "#fbfcfe", borderBottom: open ? `1px solid #eef1f6` : "none" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 14.5, fontWeight: 700, color: NAVY }}>Documents</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: MUTED, background: "#eef1f6", borderRadius: 20, padding: "2px 9px" }}>{files.length} files</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11.5, fontWeight: 600, color: GREEN }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: folderUrl ? GREEN : "#cdd5e2" }} />
          {folderUrl ? "Synced to Drive" : "No Drive folder yet"}
          {folderUrl && <a href={folderUrl} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} style={{ color: BLUE, fontWeight: 700, textDecoration: "none", marginLeft: 6 }}>Open folder ↗</a>}
        </div>
      </header>

      {open && (
        <div style={{ padding: "8px 16px 14px" }}>
          {loading && <div style={{ fontSize: 12, color: MUTED, padding: "10px 4px" }}>Loading documents…</div>}
          {!loading && files.length === 0 && (
            <div style={{ fontSize: 12, color: MUTED, padding: "10px 4px" }}>No documents yet. Prep the CPS package to pull the title + listing docs, or add one below.</div>
          )}
          {groups.map((g) => (
            <div key={g}>
              <div style={{ fontSize: 10.5, fontWeight: 800, color: "#9aa4b8", textTransform: "uppercase", letterSpacing: 0.5, margin: "14px 0 4px" }}>
                {g}{GROUP_NOTE[g] ? ` · ${GROUP_NOTE[g]}` : ""}
              </div>
              {files.filter((f) => grp(f) === g).map((f, i) => {
                const [bg, fg] = TAG_COLOR[f.tag] || ["#eef1f6", "#5a6478"];
                // The whole row is the link — tap anywhere on a doc to open the
                // actual file in Drive.
                return (
                  <a key={f.id} href={f.url} target="_blank" rel="noreferrer" style={{ display: "flex", alignItems: "center", gap: 13, padding: "10px 4px", borderTop: i ? "1px solid #f3f5f9" : "none", textDecoration: "none", cursor: "pointer" }}>
                    <span style={{ width: 34, height: 40, borderRadius: 6, flex: "0 0 auto", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 800,
                      background: isFolder(f.mime) ? "#fff6e8" : isImg(f.mime) ? "#eaf2fb" : "#fdecec",
                      border: `1px solid ${isFolder(f.mime) ? "#f0d9b0" : isImg(f.mime) ? "#d3e3f6" : "#f6d4d4"}`,
                      color: isFolder(f.mime) ? TERRA : isImg(f.mime) ? "#3b7" : "#d44" }}>
                      {isFolder(f.mime) ? "DIR" : isImg(f.mime) ? "IMG" : "PDF"}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 700, color: NAVY }}>{f.name}</div>
                      <div style={{ fontSize: 11.5, color: MUTED, marginTop: 2 }}>added {f.modified}</div>
                    </div>
                    {f.tag && <span style={{ fontSize: 10, fontWeight: 700, borderRadius: 5, padding: "2px 8px", background: bg, color: fg }}>{f.tag}</span>}
                    <span style={{ fontSize: 12.5, fontWeight: 700, color: BLUE, whiteSpace: "nowrap" }}>Open ↗</span>
                  </a>
                );
              })}
            </div>
          ))}
          {folderUrl && (
            <a href={folderUrl} target="_blank" rel="noreferrer" style={{ marginTop: 14, border: "2px dashed #c7d0e0", borderRadius: 10, padding: 13, display: "flex", alignItems: "center", gap: 12, background: "#fafbfd", textDecoration: "none" }}>
              <span style={{ width: 28, height: 28, borderRadius: 7, background: NAVY, color: "#fff", fontSize: 18, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", flex: "0 0 auto", lineHeight: 1 }}>+</span>
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: NAVY }}>Add a document</div>
                <div style={{ fontSize: 11, color: MUTED, marginTop: 1 }}>Opens the Drive folder — drop a PDF in there and it shows up here.</div>
              </div>
            </a>
          )}
          {missing && missing.length > 0 && (
            <div style={{ fontSize: 11.5, color: TERRA, marginTop: 12, paddingTop: 10, borderTop: "1px solid #f3f5f9" }}>
              <b>Still needed:</b> {missing.join(" · ")}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
