import { describe, expect, it, vi } from "vitest";
import { indexProfileDrafts, sameReviewedDraft, submitReviewedDrafts } from "../draft-selection";
import type { LeadsDraft, LeadsProfile } from "../leads-data";

const profile = (id: string, contactIds: string[], name = "Alex") => ({ id, name, contactIds } as LeadsProfile);
const draft = (id: string, contactId?: string): LeadsDraft => ({ id, contactId, name: "Alex", body: "A personal reply", source: "CRM", sourceId: "crm", taskId: id, channel: "SMS", age: "1h", heat: "warm" });

describe("reply selection", () => {
  it("matches contact IDs even when names differ, never names alone", () => {
    const people = [profile("p1", ["c1"], "Alex Smith"), profile("p2", ["c2"])];
    const result = indexProfileDrafts(people, [draft("d1", "c1"), draft("d2")]);
    expect(result.get("p1")?.map((d) => d.id)).toEqual(["d1"]);
    expect(result.has("p2")).toBe(false);
  });
  it("holds ambiguous contact matches and does not use a thread to override a conflicting contact", () => {
    const people = [profile("p1", ["c1"]), profile("p2", ["c1"])];
    expect(indexProfileDrafts(people, [draft("d1", "c1")]).size).toBe(0);
    expect(indexProfileDrafts([{...people[0], sourceId:"crm", threadId:"t1"}], [{...draft("d2","other"),threadId:"t1"}]).size).toBe(0);
  });
  it("uses exact source/thread identity when no contact is supplied and deduplicates drafts", () => {
    const d = {...draft("d1"),threadId:"t1"};
    const result = indexProfileDrafts([{...profile("p1",[]),threadIds:["crm:t1"]}], [d,d]);
    expect(result.get("p1")).toEqual([d]);
  });
  it("falls back to exact source/thread identity when CRM draft contact id is a provider id", () => {
    const d = {...draft("d1", "lofty-provider-id"), threadId: "lofty-lead:lofty-provider-id"};
    const result = indexProfileDrafts(
      [{...profile("email:alex@example.com", ["internal-db-contact-id"]), threadIds: ["crm:lofty-lead:lofty-provider-id"]}],
      [d],
    );
    expect(result.get("email:alex@example.com")).toEqual([d]);
  });
  it("invalidates the review when recipient, copy or channel changes", () => {
    const d = draft("d1","c1");
    expect(sameReviewedDraft(d,{...d})).toBe(true);
    for (const edit of [{body:"Changed"},{channel:"EMAIL"},{contactId:"c2"},{taskId:"new"}]) {
      expect(sameReviewedDraft(d,{...d,...edit})).toBe(false);
    }
  });
  it("submits only the chosen copies once, in order", async () => {
    const one=draft("one"),two=draft("two");
    const submit=vi.fn(async(_draft: LeadsDraft)=>{}), accepted=vi.fn();
    const result=await submitReviewedDrafts([one,two,one],submit,accepted);
    expect(submit.mock.calls.map((call)=>call[0])).toEqual([one,two]);
    expect(result.accepted).toEqual(["one","two"]);
    expect(accepted).toHaveBeenCalledTimes(2);
  });
  it("stops at an uncertain failure and never retries or submits later replies", async () => {
    const submit=vi.fn(async(d:LeadsDraft)=>{if(d.id==="two")throw new Error("Connection lost");});
    const result=await submitReviewedDrafts([draft("one"),draft("two"),draft("three")],submit,vi.fn());
    expect(result).toEqual({accepted:["one"],stoppedAt:"two",error:"Connection lost"});
    expect(submit.mock.calls.map(([d])=>d.id)).toEqual(["one","two"]);
  });
});
