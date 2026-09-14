// @vitest-environment happy-dom
import {createElement as h, useRef} from "react";
import {afterEach,expect,it,vi} from "vitest";
import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {useDialogFocus} from "../use-dialog-focus";
afterEach(cleanup);
function Dialog({name,close}:{name:string;close:()=>void}){const ref=useRef<HTMLDivElement>(null);useDialogFocus({dialogRef:ref,onEscape:close});return h('div',{ref,role:'dialog','aria-modal':true,'aria-label':name},h('button',{},name+' first'),h('button',{},name+' last'));}
it('does not reset focus when the parent supplies a new callback',()=>{const app=render(h(Dialog,{name:'one',close:()=>{}}));screen.getByText('one last').focus();app.rerender(h(Dialog,{name:'one',close:()=>{}}));expect(document.activeElement).toBe(screen.getByText('one last'));});
it('Escape closes only the top modal',()=>{const parent=vi.fn(),child=vi.fn();render(h('div',{},h(Dialog,{name:'parent',close:parent}),h(Dialog,{name:'child',close:child})));fireEvent.keyDown(document,{key:'Escape'});expect(child).toHaveBeenCalledOnce();expect(parent).not.toHaveBeenCalled();});
