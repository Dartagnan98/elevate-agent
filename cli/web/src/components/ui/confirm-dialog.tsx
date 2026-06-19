import { useRef } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useDialogFocus } from "@/components/ui/use-dialog-focus";

export function ConfirmDialog({
  cancelLabel = "Cancel",
  confirmLabel = "Confirm",
  description,
  destructive = false,
  loading = false,
  onCancel,
  onConfirm,
  open,
  title,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useDialogFocus({
    active: open,
    dialogRef,
    initialFocusSelector: "[data-confirm]",
    onEscape: onCancel,
  });

  if (!open) return null;

  return createPortal(
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby={description ? "confirm-dialog-desc" : undefined}
      tabIndex={-1}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center",
        "bg-black/60",
        "animate-[fade-in_150ms_ease-out]",
      )}
    >
      <div
        className={cn(
          "relative w-full max-w-md mx-4",
          "overflow-hidden rounded-md border border-border bg-card",
          "animate-[dialog-in_180ms_ease-out]",
        )}
      >
        <div className="flex items-start gap-3 border-b border-border p-4">
          {destructive && (
            <div
              aria-hidden
              className="mt-0.5 shrink-0 text-destructive"
            >
              <AlertTriangle className="h-4 w-4" />
            </div>
          )}

          <div className="flex-1 min-w-0 flex flex-col gap-1">
            <h2
              id="confirm-dialog-title"
              className="text-sm font-semibold tracking-normal text-foreground"
            >
              {title}
            </h2>

            {description && (
              <p
                id="confirm-dialog-desc"
                className="text-xs leading-relaxed text-muted-foreground"
              >
                {description}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 p-3">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onCancel}
            disabled={loading}
          >
            {cancelLabel}
          </Button>
          <Button
            data-confirm
            type="button"
            variant={destructive ? "destructive" : "default"}
            size="sm"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? "…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

interface ConfirmDialogProps {
  cancelLabel?: string;
  confirmLabel?: string;
  description?: string;
  destructive?: boolean;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  open: boolean;
  title: string;
}
