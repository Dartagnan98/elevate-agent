// @vitest-environment happy-dom
import { createElement } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ActionNeededPopup from "../ActionNeededPopup";
import { fetchJSON } from "@/lib/api";
vi.mock("@/lib/api", () => ({fetchJSON:vi.fn(),api:{approveAdminActionRun:vi.fn()}}));
vi.mock("@/pages/real-estate-hub/admin/components/waiting-card", () => ({default:({run}:any)=>createElement("div",null,run.humanPrompt.title)}));
afterEach(()=>{cleanup();vi.useRealTimers();vi.clearAllMocks();});
const queue=(title:string)=>({documents:[],gates:[{runId:"same-run",dealId:"ellis",title,humanPrompt:{title},hasPreview:title==="Review listing drafts"}]});
it("keeps an unchanged ask minimized and reopens for a new review on the same run",async()=>{
  vi.useFakeTimers();
  vi.mocked(fetchJSON).mockResolvedValue(queue("Listing commission"));
  await act(async()=>{render(createElement(ActionNeededPopup));});
  fireEvent.click(screen.getByRole("button",{name:"Minimize"}));
  await act(async()=>{await vi.advanceTimersByTimeAsync(20_000);});
  expect(screen.queryByRole("region",{name:"Actions needed"})).toBeNull();
  vi.mocked(fetchJSON).mockResolvedValue(queue("Review listing drafts"));
  await act(async()=>{await vi.advanceTimersByTimeAsync(20_000);});
  expect(screen.getByRole("region",{name:"Actions needed"})).toBeTruthy();
  expect(screen.getByText("Review listing drafts")).toBeTruthy();
});
it("reopens a run that leaves the waiting queue and later returns",async()=>{
  vi.useFakeTimers();
  vi.mocked(fetchJSON).mockResolvedValue(queue("Review listing drafts"));
  await act(async()=>{render(createElement(ActionNeededPopup));});
  fireEvent.click(screen.getByRole("button",{name:"Minimize"}));
  vi.mocked(fetchJSON).mockResolvedValue({documents:[],gates:[]});
  await act(async()=>{await vi.advanceTimersByTimeAsync(20_000);});
  vi.mocked(fetchJSON).mockResolvedValue(queue("Review listing drafts"));
  await act(async()=>{await vi.advanceTimersByTimeAsync(20_000);});
  expect(screen.getByRole("button",{name:"Minimize"})).toBeTruthy();
});
it("reopens when the PDFs change even if the review title stays the same",async()=>{
  vi.useFakeTimers();
  const version=(hash:string)=>({documents:[{runId:"review",dealId:"ellis",title:"Review listing drafts",humanPrompt:{title:"Review listing drafts",documentReview:{kit:"listing",versionHash:hash,documents:[{id:"mlc",name:"MLC"}]}}}],gates:[]});
  vi.mocked(fetchJSON).mockResolvedValue(version("first-pdf"));
  await act(async()=>{render(createElement(ActionNeededPopup));});
  fireEvent.click(screen.getByRole("button",{name:"Minimize"}));
  vi.mocked(fetchJSON).mockResolvedValue(version("revised-pdf"));
  await act(async()=>{await vi.advanceTimersByTimeAsync(20_000);});
  expect(screen.getByRole("region",{name:"Actions needed"})).toBeTruthy();
});
