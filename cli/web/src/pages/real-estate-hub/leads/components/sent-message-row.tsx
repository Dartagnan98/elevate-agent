import type { LeadsSentMessage } from "../leads-data";

export function SentMessageRow({ message }: { message: LeadsSentMessage }) {
  return (
    <div className="lb-sent-row">
      <span className="lb-sent-when mono">{message.when}</span>
      <span className="lb-sent-recipient">{message.recipient}</span>
      <span className="lb-sent-source">
        <div>{message.source}</div>
        <div className="lb-sent-transport mono">{message.transport}</div>
      </span>
      <span className="lb-sent-msg">
        <div>{message.message}</div>
        <div className="lb-sent-msg-id mono">id: {message.msgId}</div>
      </span>
      <span
        className={
          "lb-sent-status " +
          (message.status === "sent"
            ? "sent"
            : message.status === "failed"
              ? "failed"
              : "queued")
        }
      >
        {(message.status || "sent").toUpperCase()}
      </span>
    </div>
  );
}
