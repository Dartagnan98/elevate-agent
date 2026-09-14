// @vitest-environment happy-dom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ListingIntakeDocuments from "../listing-intake-documents";
import { api } from "@/lib/api";
vi.mock("@/lib/api", () => ({api:{approveAdminActionRun:vi.fn(),answerAdminActionRun:vi.fn()}}));
afterEach(() => {cleanup();vi.restoreAllMocks();});
it("shows saved intake PDFs and the same approval without approving on open", () => {
  const open=vi.spyOn(window,"open").mockImplementation(()=>null), edit=vi.fn();
  render(<MemoryRouter><ListingIntakeDocuments dealId="ellis" extra={{listingKitForms:{pds:false},listingKit:{documents:[
    {id:"mlc",name:"Multiple Listing Contract",filePath:"/draft.pdf",ready:true},
    {id:"dorts",name:"DORTS"},{id:"pds",name:"Excluded PDS",filePath:"/pds.pdf"}]}}}
    runs={[{id:"review",status:"waiting_human",humanPrompt:{title:"Review listing drafts",documentReview:{kit:"listing",documents:[{id:"mlc",name:"MLC"}]},actionLabel:"Approve drafts for signature setup"}}]}
    onOpen={edit} onResolved={()=>{}}/></MemoryRouter>);
  expect(screen.getByRole("region",{name:"Listing Intake documents"})).toBeTruthy();
  expect(screen.queryByText("Excluded PDS")).toBeNull();
  expect(screen.getByText("Not prepared yet")).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button",{name:"Open MLC ↗"})[0]);
  expect(open.mock.calls[0][0]).toContain("/api/admin/deals/ellis/listing-kit-doc/mlc");
  expect(api.approveAdminActionRun).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Review / edit listing documents →"}));
  expect(edit).toHaveBeenCalledOnce();
  expect(screen.getByRole("button",{name:"Approve drafts for signature setup"})).toBeTruthy();
});
