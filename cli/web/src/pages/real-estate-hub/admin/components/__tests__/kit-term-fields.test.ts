import { describe,it,expect } from "vitest";
import { dateValue,toggleIncluded } from "../kit-term-fields";

describe('document term entry',()=>{
  it('keeps an explicit date without timezone shifts and refuses to guess shorthand years',()=>{
    expect(dateValue('2026-10-01')).toBe('2026-10-01');
    expect(dateValue('Jul 14')).toBe('');
    expect(dateValue('2026-02-30')).toBe('');
    expect(dateValue('2028-02-29')).toBe('2028-02-29');
  });
  it('adds and removes choices while retaining custom contractual wording',()=>{
    const original='Furniture listed in Schedule A, except the oak desk';
    expect(toggleIncluded(original,'Refrigerator',true)).toBe(original+'; Refrigerator');
    expect(toggleIncluded(original+'; Refrigerator','Refrigerator',false)).toBe(original);
    expect(toggleIncluded('Refrigerator','Refrigerator',true)).toBe('Refrigerator');
  });
});
