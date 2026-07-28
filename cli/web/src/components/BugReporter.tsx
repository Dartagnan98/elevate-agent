import { useCallback, useEffect, useRef, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { fetchJSON } from "@/lib/api";
import { installRecentErrorCapture, recentErrors } from "@/lib/recent-errors";
import { cn } from "@/lib/utils";
import { Bug, Check, ImageUp, Loader2, RefreshCw } from "lucide-react";

// Downscale any image blob/file to a small JPEG data URL, matching the
// auto-capture path so uploaded/pasted shots stay under the backend cap.
async function imageBlobToDataUrl(blob: Blob): Promise<string | null> {
  try {
    const bitmap = await createImageBitmap(blob);
    const maxW = 1400;
    const ratio = bitmap.width > maxW ? maxW / bitmap.width : 1;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * ratio);
    canvas.height = Math.round(bitmap.height * ratio);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    // white backing so PNGs with transparency don't turn black in the JPEG
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();
    return canvas.toDataURL("image/jpeg", 0.85);
  } catch {
    return null;
  }
}

/**
 * Top-right "Report a bug" widget, present on every dashboard page.
 * Click -> grabs a screenshot of the current screen -> small modal with a note
 * box + the screenshot -> POST /api/bug-reports. She can also drop / paste /
 * upload a different image (e.g. a native macOS region screenshot of one
 * specific thing) to replace the auto-capture, or recapture the page.
 * Page/account/error context is attached silently so non-technical reporters
 * don't have to describe anything technical. Reports land in the Bug Reports
 * list (sidebar -> More).
 */
export function BugReporter() {
  const [open, setOpen] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [note, setNote] = useState("");
  const [shot, setShot] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [doneNumber, setDoneNumber] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const doneTimer = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    installRecentErrorCapture();
    return () => {
      if (doneTimer.current) window.clearTimeout(doneTimer.current);
    };
  }, []);

  const captureScreenshot = useCallback(async (): Promise<string | null> => {
    try {
      // modern-screenshot renders through the browser's own SVG engine, so it
      // handles this app's modern CSS (color-mix / oklch) that html2canvas can't.
      const { domToCanvas } = await import("modern-screenshot");
      const canvas = await domToCanvas(document.body, {
        backgroundColor: null,
        scale: Math.min(window.devicePixelRatio || 1, 1.5),
        // skip our own portal/button so they aren't painted into the shot
        filter: (node) =>
          !(node instanceof Element &&
            node.getAttribute?.("data-bug-reporter") === "true"),
      });
      // downscale so the payload stays small
      const maxW = 1400;
      let out: HTMLCanvasElement = canvas;
      if (canvas.width > maxW) {
        const scaled = document.createElement("canvas");
        const ratio = maxW / canvas.width;
        scaled.width = maxW;
        scaled.height = Math.round(canvas.height * ratio);
        const ctx = scaled.getContext("2d");
        if (ctx) {
          ctx.drawImage(canvas, 0, 0, scaled.width, scaled.height);
          out = scaled;
        }
      }
      return out.toDataURL("image/jpeg", 0.82);
    } catch {
      return null; // best-effort — a report with no screenshot is fine
    }
  }, []);

  const openReporter = useCallback(async () => {
    if (capturing) return;
    setError(null);
    setDoneNumber(null);
    setNote("");
    setShot(null);
    // Capture the clean page FIRST, before the modal + its dimmed backdrop are
    // on screen (the Modal renders through a portal, so it can't be excluded by
    // a wrapper). The button itself is tagged data-bug-reporter and filtered out.
    setCapturing(true);
    const img = await captureScreenshot();
    setShot(img);
    setCapturing(false);
    setOpen(true);
  }, [captureScreenshot, capturing]);

  // Re-grab a fresh capture of the page while the modal is open. Hide the modal
  // first so the dimmed backdrop isn't painted into the shot, then restore it.
  const recapture = useCallback(async () => {
    if (capturing) return;
    setError(null);
    setOpen(false);
    setCapturing(true);
    // let the modal unmount + repaint before grabbing
    await new Promise((r) => window.setTimeout(r, 120));
    const img = await captureScreenshot();
    setShot(img);
    setCapturing(false);
    setOpen(true);
  }, [captureScreenshot, capturing]);

  const loadImageFile = useCallback(async (file: File | null | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("That's not an image file. Use a PNG, JPG, or WebP.");
      return;
    }
    setError(null);
    setCapturing(true);
    const url = await imageBlobToDataUrl(file);
    setCapturing(false);
    if (url) setShot(url);
    else setError("Couldn't read that image. Try a different file.");
  }, []);

  // Paste an image straight from the clipboard (macOS Cmd+Shift+4 to clipboard,
  // then Cmd+V here) while the modal is open.
  useEffect(() => {
    if (!open) return;
    const onPaste = (e: ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.items || []).find((i) =>
        i.type.startsWith("image/"),
      );
      if (item) {
        e.preventDefault();
        loadImageFile(item.getAsFile() || undefined);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [open, loadImageFile]);

  const close = useCallback(() => {
    if (doneTimer.current) window.clearTimeout(doneTimer.current);
    setOpen(false);
    setShot(null);
    setNote("");
    setSubmitting(false);
    setDoneNumber(null);
    setError(null);
  }, []);

  const dealMatch = window.location.pathname.match(/\/admin\/deals?\/([^/]+)/);

  const submit = useCallback(async () => {
    if (!note.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetchJSON<{ ok: boolean; number: number }>(
        "/api/bug-reports",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            note: note.trim(),
            screenshot: shot,
            page: window.location.pathname + window.location.search,
            pageTitle: document.title,
            dealId: dealMatch?.[1] ?? null,
            userAgent: navigator.userAgent,
            viewport: `${window.innerWidth}x${window.innerHeight}`,
            consoleErrors: recentErrors(),
          }),
        },
      );
      setDoneNumber(res.number ?? 0);
      doneTimer.current = window.setTimeout(close, 1800);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not send. Please try again.",
      );
      setSubmitting(false);
    }
  }, [note, shot, submitting, close, dealMatch]);

  return (
    <>
      <button
        type="button"
        data-bug-reporter="true"
        onClick={openReporter}
        title="Report a bug"
        aria-label="Report a bug"
        className={cn(
          "fixed right-3 top-2 z-[45] hidden items-center gap-2 rounded-full sm:flex",
          "border border-[#5E8AD0]/50 bg-[#5E8AD0]/10 px-3 py-1.5 backdrop-blur-sm",
          "text-xs font-medium text-[#5E8AD0] shadow-sm transition-colors",
          "hover:border-[#5E8AD0] hover:bg-[#5E8AD0]/20",
        )}
      >
        {capturing ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Bug className="h-4 w-4" aria-hidden="true" />
        )}
        {capturing ? "Grabbing screenshot…" : "Report a bug"}
      </button>

      {/* mobile: icon-only, tucked top-right */}
      <button
        type="button"
        data-bug-reporter="true"
        onClick={openReporter}
        title="Report a bug"
        aria-label="Report a bug"
        className="fixed right-2 top-2.5 z-[45] flex h-9 w-9 items-center justify-center rounded-full border border-[#5E8AD0]/50 bg-[#5E8AD0]/10 text-[#5E8AD0] backdrop-blur-sm shadow-sm sm:hidden"
      >
        {capturing ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          <Bug className="h-5 w-5" aria-hidden="true" />
        )}
      </button>

      {open && (
        <div data-bug-reporter="true">
          <Modal title="Report a bug" onClose={close}>
            {doneNumber !== null ? (
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[#5E8AD0]/15">
                  <Check className="h-6 w-6 text-[#5E8AD0]" />
                </div>
                <p className="text-sm font-medium text-foreground">
                  Sent to Skyleigh — report #{doneNumber}
                </p>
                <p className="text-xs text-muted-foreground">
                  Thanks. It's saved to the Bug Reports list.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <label className="block text-xs font-medium text-muted-foreground">
                  What's going on?
                </label>
                <textarea
                  data-autofocus
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
                  }}
                  rows={4}
                  placeholder="e.g. this step takes too many clicks, or the Approve button is hard to find here"
                  className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
                />

                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    loadImageFile(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />

                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    loadImageFile(e.dataTransfer.files?.[0]);
                  }}
                  className={cn(
                    "rounded-md border border-border bg-background/50 p-2 transition-colors",
                    dragging && "border-[#5E8AD0] bg-[#5E8AD0]/10",
                  )}
                >
                  {capturing ? (
                    <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Grabbing a screenshot…
                    </div>
                  ) : shot ? (
                    <div className="flex items-start gap-3">
                      <img
                        src={shot}
                        alt="Screenshot preview"
                        className="h-20 w-auto max-w-[60%] rounded border border-border object-contain"
                      />
                      <div className="flex flex-col gap-1.5 text-xs">
                        <span className="text-muted-foreground">
                          Screenshot attached
                        </span>
                        <button
                          type="button"
                          onClick={() => fileInputRef.current?.click()}
                          className="w-fit text-[#5E8AD0] hover:underline"
                        >
                          Upload a different image
                        </button>
                        <button
                          type="button"
                          onClick={recapture}
                          className="w-fit text-[#5E8AD0] hover:underline"
                        >
                          Recapture this page
                        </button>
                        <button
                          type="button"
                          onClick={() => setShot(null)}
                          className="w-fit text-muted-foreground hover:underline"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-2 py-3 text-center">
                      <ImageUp className="h-5 w-5 text-muted-foreground/70" />
                      <p className="text-xs text-muted-foreground">
                        Drag an image here, paste it (Cmd+V), or
                      </p>
                      <div className="flex gap-3 text-xs">
                        <button
                          type="button"
                          onClick={() => fileInputRef.current?.click()}
                          className="inline-flex items-center gap-1 text-[#5E8AD0] hover:underline"
                        >
                          <ImageUp className="h-3.5 w-3.5" /> Upload image
                        </button>
                        <button
                          type="button"
                          onClick={recapture}
                          className="inline-flex items-center gap-1 text-[#5E8AD0] hover:underline"
                        >
                          <RefreshCw className="h-3.5 w-3.5" /> Capture this page
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                <p className="text-[11px] leading-tight text-muted-foreground/80">
                  Tip: press Cmd+Shift+4 to snap one specific thing, then paste or
                  drop it here. Page, account, and error details attach
                  automatically.
                </p>

                {error && (
                  <p className="text-xs text-destructive">{error}</p>
                )}

                <div className="flex justify-end gap-2 pt-1">
                  <Button variant="ghost" size="sm" onClick={close}>
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    onClick={submit}
                    disabled={!note.trim() || submitting || capturing}
                    className="bg-[#5E8AD0] text-white hover:bg-[#4a76bc]"
                  >
                    {submitting ? (
                      <span className="flex items-center gap-1.5">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Sending…
                      </span>
                    ) : (
                      "Send"
                    )}
                  </Button>
                </div>
              </div>
            )}
          </Modal>
        </div>
      )}
    </>
  );
}
