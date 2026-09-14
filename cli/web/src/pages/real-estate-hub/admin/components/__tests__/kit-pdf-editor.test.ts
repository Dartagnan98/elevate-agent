import {describe,it,expect} from "vitest";
import {changedPdfFields,pdfInitialValues,type PdfPage} from "../kit-pdf-editor";
describe("PDF edits",()=>{
 it("keeps a deliberate clear and omits unchanged values",()=>{
  expect(changedPdfFields({buyer:"Name",price:"500"},{buyer:"",price:"500"})).toEqual({buyer:""});
 });
 it("does not send an edit after the original value is restored",()=>{
  expect(changedPdfFields({buyer:"Name"},{buyer:"Name"})).toEqual({});
 });
 it("keeps the selected value when a later widget in the same group is unchecked",()=>{
  const pages=[{fields:[{name:"representation",type:"choice",value:"1"},{name:"representation",type:"choice",value:""}]}] as PdfPage[];
  expect(pdfInitialValues(pages)).toEqual({representation:"1"});
 });
});
