import { ListSkeleton } from "@/components/ui/skeleton";

export type ProfileDrawerMessage = {
  id: string;
  direction: "in" | "out";
  from: string;
  text: string;
  time: string;
};

export function ProfileDrawerThread({
  loading,
  error,
  messages,
}: {
  loading: boolean;
  error: string | null;
  messages: ProfileDrawerMessage[];
}) {
  return (
    <div className="lb-drawer-thread">
      {loading ? (
        <ListSkeleton rows={4} />
      ) : error ? (
        <div className="lb-drawer-empty">{error}</div>
      ) : messages.length === 0 ? (
        <div className="lb-drawer-empty">No messages on file yet.</div>
      ) : (
        messages.map((m) => (
          <div key={m.id} className={"lb-drawer-msg " + m.direction}>
            <div className="lb-drawer-msg-head mono">
              {m.from} · {m.time}
            </div>
            <div className="lb-drawer-msg-text">{m.text}</div>
          </div>
        ))
      )}
    </div>
  );
}
