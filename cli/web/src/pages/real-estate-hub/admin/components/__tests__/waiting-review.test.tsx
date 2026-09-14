// @vitest-environment happy-dom
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WaitingCard from '../waiting-card';
const mocks = vi.hoisted(() => ({approve: vi.fn(), answer: vi.fn(), resolveSurface: vi.fn()}));
vi.mock('@/lib/api', () => ({api:{approveAdminActionRun:mocks.approve, answerAdminActionRun:mocks.answer, resolveSurfaceApproval:mocks.resolveSurface}}));
const base = {runId:'review-1',dealId:'deal-1',humanPrompt:{title:'Review Collingwood',sessionId:'chat-1',reviewPackage:{mode:'publish',artifacts:[{path:'/outputs/landing.html',name:'Landing page'},{path:'/outputs/tour.mp4',name:'Video'}],actions:[{id:'publish_landing',label:'Publish landing page',details:'https://example.com/listing/'}]}}};
afterEach(cleanup);
beforeEach(() => {vi.clearAllMocks();mocks.approve.mockResolvedValue({});mocks.answer.mockResolvedValue({});});
describe('Marketing review card', () => {
 it('opens exact files in the originating chat preview bar', () => {
  render(<MemoryRouter><WaitingCard run={base}/></MemoryRouter>);
  expect(screen.getByRole('link',{name:'Preview Video'}).getAttribute('href')).toBe('/chat?resume=chat-1&artifact=%2Foutputs%2Ftour.mp4');
  expect(screen.getByText('https://example.com/listing/')).toBeTruthy();
 });
 it('approves only its own action run and does not resolve unrelated approvals', async () => {
  render(<MemoryRouter><WaitingCard run={base}/></MemoryRouter>);
  fireEvent.click(screen.getByRole('button',{name:'Approve listed actions'}));
  await waitFor(() => expect(mocks.approve).toHaveBeenCalledWith('review-1',{approved:true,runNow:true}));
  expect(mocks.resolveSurface).not.toHaveBeenCalled();
 });
 it('collects missing launch timing without presenting publish approval', async () => {
  const run={...base,humanPrompt:{...base.humanPrompt,requiredFields:[{label:'Launch timing'}],reviewPackage:{...base.humanPrompt.reviewPackage,mode:'prepare',actions:[]}}};
  render(<MemoryRouter><WaitingCard run={run}/></MemoryRouter>);
  expect(screen.queryByRole('button',{name:'Approve listed actions'})).toBeNull();
  fireEvent.change(screen.getByPlaceholderText('Type Launch timing…'),{target:{value:'Tomorrow at 10 AM Pacific'}});
  fireEvent.click(screen.getByRole('button',{name:'Prepare final approval'}));
  await waitFor(() => expect(mocks.answer).toHaveBeenCalledWith('review-1',{answers:{'Launch timing':'Tomorrow at 10 AM Pacific'},runNow:true}));
 });
});
