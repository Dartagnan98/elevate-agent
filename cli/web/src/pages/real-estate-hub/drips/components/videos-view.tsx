import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { DripVideo } from "@/lib/api";
import { errorMessage } from "../drips-helpers";
import { Field, Note, Section, fieldClass } from "./shared";

export function VideosView({ onChanged }: { onChanged: () => Promise<void> | void }) {
  const [videos, setVideos] = useState<DripVideo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ name: "", script: "", lengthLabel: "" });

  const load = async () => {
    try {
      const res = await api.getDripVideos();
      setVideos(res.videos);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "Could not load the video library."));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await load();
      await onChanged();
      return true;
    } catch (err) {
      setError(errorMessage(err, "Could not save the video."));
      return false;
    } finally {
      setBusy(null);
    }
  };

  const recorded = videos?.filter((v) => v.link).length ?? 0;

  return (
    <Section
      title="Video script library"
      hint={`Every video in every campaign, scripted once. Record it, paste the link, and every touch that names it picks the link up. ${recorded} of ${videos?.length ?? 0} recorded.`}
      actions={
        <Button size="sm" onClick={() => setAdding(true)} disabled={adding}>
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          Add a video
        </Button>
      }
    >
      {error && <Note tone="error" className="mb-3">{error}</Note>}
      {adding && (
        <div className="mb-3 grid gap-3 rounded-md border border-border bg-muted/20 p-3 md:grid-cols-2">
          <Field label="Name">
            <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Neighbourhood tour" />
          </Field>
          <Field label="Length">
            <Input value={draft.lengthLabel} onChange={(e) => setDraft({ ...draft, lengthLabel: e.target.value })} placeholder="45 to 60 seconds" />
          </Field>
          <Field label="Script" className="md:col-span-2">
            <textarea className={fieldClass} rows={4} value={draft.script} onChange={(e) => setDraft({ ...draft, script: e.target.value })} />
          </Field>
          <div className="flex justify-end gap-2 md:col-span-2">
            <Button variant="outline" size="sm" onClick={() => setAdding(false)} disabled={busy === "new"}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={busy === "new" || !draft.name.trim()}
              onClick={() =>
                void act("new", () => api.createDripVideo({ name: draft.name, script: draft.script || undefined, lengthLabel: draft.lengthLabel || undefined })).then((ok) => {
                  if (ok) {
                    setAdding(false);
                    setDraft({ name: "", script: "", lengthLabel: "" });
                  }
                })
              }
            >
              Add
            </Button>
          </div>
        </div>
      )}
      <ul className="flex flex-col gap-2">
        {videos?.map((video) => (
          <VideoRow key={video.slug} video={video} busy={busy === video.slug} onSave={(patch) => act(video.slug, () => api.updateDripVideo(video.slug, patch))} onDelete={() => act(video.slug, () => api.deleteDripVideo(video.slug))} />
        ))}
      </ul>
    </Section>
  );
}

function VideoRow({
  video,
  busy,
  onSave,
  onDelete,
}: {
  video: DripVideo;
  busy: boolean;
  onSave: (patch: { link?: string; script?: string; name?: string }) => Promise<boolean>;
  onDelete: () => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState(video.link ?? "");
  const [script, setScript] = useState(video.script ?? "");
  const dirtyLink = link !== (video.link ?? "");
  const dirtyScript = script !== (video.script ?? "");

  return (
    <li className="rounded-md border border-border">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          {open ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />}
          <span className="text-sm font-medium text-foreground">{video.name}</span>
          {video.lengthLabel && <span className="font-mono-ui text-[0.7rem] text-muted-foreground">{video.lengthLabel}</span>}
          <Badge variant={video.link ? "success" : "warning"}>{video.link ? `recorded ${video.recordedAt ?? ""}`.trim() : "not recorded"}</Badge>
        </button>
        <div className="flex w-full items-center gap-2 sm:w-auto sm:min-w-[22rem]">
          <Input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Paste the unlisted video link" disabled={busy} aria-label={`${video.name} link`} />
          <Button size="sm" disabled={busy || !dirtyLink} onClick={() => void onSave({ link })}>
            Save
          </Button>
        </div>
      </div>
      {open && (
        <div className="flex flex-col gap-2 border-t border-border px-3 py-3">
          {video.usedIn && <p className="text-[0.72rem] text-muted-foreground">Used in: {video.usedIn}</p>}
          <textarea className={fieldClass} rows={7} value={script} onChange={(e) => setScript(e.target.value)} disabled={busy} aria-label={`${video.name} script`} />
          <div className="flex flex-wrap justify-between gap-2">
            {!video.builtin ? (
              <Button variant="ghost" size="sm" className="text-destructive" disabled={busy} onClick={() => void onDelete()}>
                Delete video
              </Button>
            ) : (
              <span />
            )}
            <Button size="sm" variant="outline" disabled={busy || !dirtyScript} onClick={() => void onSave({ script })}>
              Save script
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}
