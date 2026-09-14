// @vitest-environment happy-dom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ApprovalsQueue from "../approvals-queue";
import ListingIntakeDocuments from "../listing-intake-documents";
import { api } from "@/lib/api";
const { purchase, mlc, resource } = vi.hoisted(() => {
 const purchase={title:"Approve current title purchase",message:"Title CA7871214 for PID 028-077-580. Total $13.37 CAD.",actionLabel:"Approve title purchase — $13.37 CAD",dismissLabel:"Hold off",titleOrder:{versionHash:"quote-v1"}};
 const mlc={title:"Listing drafts need correction",actionLabel:"Approve drafts for signature setup",approvalBlockedReason:"Verify full seller legal names against title",documentReview:{kit:"listing",documents:[{id:"mlc",name:"MLC"}]}};
 return {purchase,mlc,resource:{loading:false,load:()=>{},data:{count:2,gates:[],documents:[
  {runId:"title",dealId:"ellis",address:"Ellis",humanPrompt:purchase},
  {runId:"mlc",dealId:"ellis",address:"Ellis",humanPrompt:mlc}
 ]}}};
});
vi.mock("@/lib/api",()=>({api:{approveAdminActionRun:vi.fn().mockResolvedValue({})}}));
vi.mock("../../use-desk-resource",()=>({useDeskResource:()=>resource}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
it("approves the exact paid title separately on the Action Board while MLC approval stays blocked",async()=>{
 render(<MemoryRouter><ApprovalsQueue onOpenDeal={()=>{}}/></MemoryRouter>);
 fireEvent.click(screen.getByRole("button",{name:/Approvals/}));
 expect(screen.queryByRole("checkbox")).toBeNull();
 expect((screen.getByRole("button",{name:"Approve drafts for signature setup"}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole("button",{name:"Approve title purchase — $13.37 CAD"}));
 await waitFor(()=>expect(api.approveAdminActionRun).toHaveBeenCalledExactlyOnceWith("title",{approved:true,runNow:true,expectedTitleOrderHash:"quote-v1"}));
});
it("shows the same title purchase in Listing Intake and allows holding off without approving drafts",async()=>{
 render(<MemoryRouter><ListingIntakeDocuments dealId="ellis" extra={{}} runs={[
  {id:"title",status:"waiting_human",humanPrompt:purchase},{id:"mlc",status:"waiting_human",humanPrompt:mlc}
 ]} onOpen={()=>{}} onResolved={()=>{}}/></MemoryRouter>);
 expect(screen.getByRole("button",{name:"Approve title purchase — $13.37 CAD"})).toBeTruthy();
 fireEvent.click(screen.getByRole("button",{name:"Hold off"}));
 await waitFor(()=>expect(api.approveAdminActionRun).toHaveBeenCalledExactlyOnceWith("title",{approved:false,runNow:false,expectedTitleOrderHash:"quote-v1"}));
});
