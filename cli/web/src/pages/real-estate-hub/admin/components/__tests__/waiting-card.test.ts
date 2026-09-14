// @vitest-environment happy-dom
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import WaitingCard from "../waiting-card";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { answerAdminActionRun: vi.fn().mockResolvedValue({}), approveAdminActionRun: vi.fn().mockResolvedValue({}) } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
function show(humanPrompt: Record<string, unknown>, skill = "Listing Intake: Collect MLC info") {
  return render(createElement(MemoryRouter, null, createElement(WaitingCard, {run: {runId:"intake",dealId:"deal",skill,humanPrompt}})));
}
describe("workflow-owned missing inputs", () => {
  it("keeps draft previews available while title verification blocks approval", () => {
    show({title:"Listing drafts need correction",approvalBlockedReason:"Obtain current title",documentReview:{kit:"listing",documents:[{id:"mlc",name:"MLC"}]},actionLabel:"Approve drafts for signature setup"});
    expect((screen.getByRole("button",{name:"Approve drafts for signature setup"}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button",{name:"Open MLC ↗"}) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("Obtain current title")).toBeTruthy();
  });
  it("does not manufacture photos fields from a workflow name", () => {
    show({requiredFields:["Commission terms"]});
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.queryByText(/photos/i)).toBeNull();
  });
  it("keeps explicitly requested optional photos and submits only entered answers", async () => {
    show({requiredFields:["Commission terms"],optionalFields:[{label:"Property photos",help:"Add when available"}]});
    expect(screen.getByText("Property photos (optional)")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Commission terms"),{target:{value:"Agreed commission wording"}});
    fireEvent.click(screen.getByRole("button",{name:"Submit & run"}));
    await waitFor(() => expect(api.answerAdminActionRun).toHaveBeenCalledWith("intake",{answers:{"Commission terms":"Agreed commission wording"},runNow:true}));
  });
  it("retains previous answers, permits editing, and renders dates separately", async () => {
    show({requiredFields:[{label:"Effective date",type:"date"},{label:"Expiry date",type:"date"}],providedAnswers:{"Effective date":"2026-09-11"}});
    expect((screen.getByLabelText("Effective date") as HTMLInputElement).type).toBe("date");
    expect((screen.getByLabelText("Effective date") as HTMLInputElement).value).toBe("2026-09-11");
    fireEvent.change(screen.getByLabelText("Expiry date"),{target:{value:"2027-01-11"}});
    fireEvent.click(screen.getByRole("button",{name:"Submit & run"}));
    await waitFor(() => expect(api.answerAdminActionRun).toHaveBeenCalledWith("intake",{answers:{"Effective date":"2026-09-11","Expiry date":"2027-01-11"},runNow:true}));
  });
  it("keeps approval-only cards usable without adding data questions", () => {
    show({requiredFields:["Approve sending drafted MLC"]});
    expect(screen.queryByRole("textbox")).toBeNull();
    expect((screen.getByRole("button",{name:"Approve & re-run"}) as HTMLButtonElement).disabled).toBe(false);
  });
  it("prefills workflow defaults and submits them without retyping", async () => {
    show({requiredFields:[{label:"Commission terms",type:"textarea",defaultValue:"6% first $100,000; 3% balance"}]});
    expect((screen.getByLabelText("Commission terms") as HTMLTextAreaElement).value).toBe("6% first $100,000; 3% balance");
    fireEvent.click(screen.getByRole("button",{name:"Submit & run"}));
    await waitFor(() => expect(api.answerAdminActionRun).toHaveBeenCalledWith("intake",{answers:{"Commission terms":"6% first $100,000; 3% balance"},runNow:true}));
  });
  it("keeps previous answers ahead of defaults and submits an edit", async () => {
    show({requiredFields:[{label:"Commission terms",type:"textarea",defaultValue:"Usual terms"}],providedAnswers:{"Commission terms":"Previously agreed terms"}});
    const field = screen.getByLabelText("Commission terms") as HTMLTextAreaElement;
    expect(field.value).toBe("Previously agreed terms");
    fireEvent.change(field,{target:{value:"Custom commission"}});
    fireEvent.click(screen.getByRole("button",{name:"Submit & run"}));
    await waitFor(() => expect(api.answerAdminActionRun).toHaveBeenCalledWith("intake",{answers:{"Commission terms":"Custom commission"},runNow:true}));
  });
  it("allows clearing a prefilled value without restoring the default", () => {
    show({requiredFields:[{label:"Commission terms",type:"textarea",defaultValue:"Usual terms"}]});
    const field = screen.getByLabelText("Commission terms") as HTMLTextAreaElement;
    fireEvent.change(field,{target:{value:""}});
    expect(field.value).toBe("");
    expect((screen.getByRole("button",{name:"Submit & run"}) as HTMLButtonElement).disabled).toBe(true);
  });
  it("opens each actual listing PDF without approving the package", () => {
    const open = vi.spyOn(window,"open").mockImplementation(()=>null);
    show({title:"Review listing drafts",documentReview:{kit:"listing",documents:[{id:"mlc",name:"MLC"},{id:"pds",name:"PDS"}]},actionLabel:"Approve drafts for signature setup"});
    fireEvent.click(screen.getByRole("button",{name:"Open PDS ↗"}));
    expect(open.mock.calls[0][0]).toContain("/api/admin/deals/deal/listing-kit-doc/pds?token=");
    expect(api.approveAdminActionRun).not.toHaveBeenCalled();
    expect(screen.getByRole("button",{name:"Approve drafts for signature setup"})).toBeTruthy();
    open.mockRestore();
  });
});
