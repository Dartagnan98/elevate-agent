// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useConfirmation } from "../useConfirmation";

function Harness({ onDecision }: { onDecision: (confirmed: boolean) => void }) {
  const { confirm, dialog } = useConfirmation();
  return <>{dialog}<button onClick={async () => onDecision(await confirm("Archive this lead?"))}>Archive</button></>;
}

afterEach(cleanup);

describe("action confirmations", () => {
  it("waits for confirmation before continuing", async () => {
    const onDecision = vi.fn();
    render(<Harness onDecision={onDecision} />);
    fireEvent.click(screen.getByText("Archive"));
    expect(onDecision).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog").textContent).toContain("Archive this lead?");
    await act(async () => { fireEvent.click(screen.getByText("Confirm")); });
    expect(onDecision).toHaveBeenCalledExactlyOnceWith(true);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancels on Escape", async () => {
    const onDecision = vi.fn();
    render(<Harness onDecision={onDecision} />);
    fireEvent.click(screen.getByText("Archive"));
    await act(async () => { fireEvent.keyDown(document, { key: "Escape" }); });
    expect(onDecision).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("does not carry a pending action across navigation", async () => {
    const onDecision = vi.fn();
    const view = render(<Harness onDecision={onDecision} />);
    fireEvent.click(screen.getByText("Archive"));
    await act(async () => { view.unmount(); });
    expect(onDecision).toHaveBeenCalledExactlyOnceWith(false);
  });
});
