// @vitest-environment happy-dom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ApprovalsQueue from "../approvals-queue";
import { api } from "@/lib/api";
vi.mock("@/lib/api", () => ({api:{approveAdminActionRun:vi.fn()}}));
vi.mock("../../use-desk-resource", () => { const resource = {
  loading:false, load:vi.fn(), data:{count:1,gates:[],documents:[{
    runId:"r",dealId:"ellis",address:"Ellis",side:"Listing",title:"Review drafts",message:"Drafts below",hasPreview:true,outbound:false,
    humanPrompt:{title:"Review drafts",actionLabel:"Approve drafts for signature setup",documentReview:{kit:"listing",documents:[{id:"mlc",name:"MLC"},{id:"pds",name:"PDS"}]}}
  }]}
}; return {useDeskResource:()=>resource}; });
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it("shows draft links on the board and keeps document review out of bulk approval",()=>{
 const open=vi.spyOn(window,"open").mockImplementation(()=>null);
 render(<MemoryRouter><ApprovalsQueue onOpenDeal={vi.fn()}/></MemoryRouter>);
 fireEvent.click(screen.getByRole("button",{name:/Approvals/}));
 fireEvent.click(screen.getByRole("button",{name:"Open MLC ↗"}));
 expect(open.mock.calls[0][0]).toContain("/api/admin/deals/ellis/listing-kit-doc/mlc?");
 expect(screen.getByRole("button",{name:"Open PDS ↗"})).toBeTruthy();
 expect(screen.queryByRole("checkbox")).toBeNull();
 expect(api.approveAdminActionRun).not.toHaveBeenCalled();
});
