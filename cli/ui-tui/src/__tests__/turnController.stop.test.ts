import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import { resetOverlayState } from '../app/overlayStore.js'
import { turnController } from '../app/turnController.js'
import { getTurnState, patchTurnState, resetTurnState } from '../app/turnStore.js'
import { getUiState, patchUiState, resetUiState } from '../app/uiStore.js'
import type { SessionStopResponse } from '../gatewayTypes.js'
import type { Msg } from '../types.js'

const ref = <T>(current: T) => ({ current })

const deferred = <T>() => {
  let reject!: (error: unknown) => void
  let resolve!: (value: T) => void

  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })

  return { promise, reject, resolve }
}

const buildEventContext = (appended: Msg[], sys = vi.fn()) =>
  ({
    composer: {
      dequeue: () => undefined,
      queueEditRef: ref<null | number>(null),
      sendQueued: vi.fn(),
      setInput: vi.fn()
    },
    gateway: {
      gw: { request: vi.fn() },
      rpc: vi.fn(async () => null)
    },
    session: {
      STARTUP_RESUME_ID: '',
      colsRef: ref(80),
      newSession: vi.fn(),
      resetSession: vi.fn(),
      resumeById: vi.fn(),
      setCatalog: vi.fn()
    },
    submission: {
      submitRef: { current: vi.fn() }
    },
    system: {
      bellOnComplete: false,
      sys
    },
    transcript: {
      appendMessage: (msg: Msg) => appended.push(msg),
      panel: vi.fn(),
      setHistoryItems: vi.fn()
    },
    voice: {
      setProcessing: vi.fn(),
      setRecording: vi.fn(),
      setVoiceEnabled: vi.fn()
    }
  }) as any

const stopDeps = (
  request: ReturnType<typeof vi.fn>,
  appended: Msg[] = [],
  sys: ReturnType<typeof vi.fn> = vi.fn()
) => ({
  appendMessage: (msg: Msg) => appended.push(msg),
  gw: { request },
  sid: 'session-1',
  sys
})

describe('terminal Stop lifecycle', () => {
  beforeEach(() => {
    resetOverlayState()
    resetUiState()
    resetTurnState()
    turnController.fullReset()
    patchUiState({ busy: true, sid: 'session-1', status: 'running…' })
  })

  it('requests session.stop without settling or synthesizing the transcript', async () => {
    const rpc = deferred<SessionStopResponse>()
    const request = vi.fn(() => rpc.promise)
    const appended: Msg[] = []

    turnController.bufRef = 'partial answer'
    turnController.segmentMessages = [{ role: 'assistant', text: 'earlier segment' }]
    patchTurnState({
      streamSegments: [{ role: 'assistant', text: 'earlier segment' }],
      streaming: 'partial answer'
    })

    const stopping = turnController.interruptTurn(stopDeps(request, appended))

    expect(request).toHaveBeenCalledWith('session.stop', { session_id: 'session-1' })
    expect(appended).toEqual([])
    expect(getTurnState()).toMatchObject({
      streamSegments: [{ role: 'assistant', text: 'earlier segment' }],
      streaming: 'partial answer'
    })
    expect(getUiState()).toMatchObject({ busy: true, status: 'stopping…' })

    rpc.resolve({ quiesced: true, running: false, status: 'stopped' })
    await stopping

    // Even a quiesced Stop acknowledgement is not the transcript's terminal
    // event. The fenced message.complete remains the only settlement point.
    expect(appended).toEqual([])
    expect(getUiState()).toMatchObject({ busy: true, status: 'stopping…' })
  })

  it('keeps Stop single-flight across Ctrl+C and double-empty input', async () => {
    const rpc = deferred<SessionStopResponse>()
    const request = vi.fn(() => rpc.promise)
    const deps = stopDeps(request)

    const ctrlC = turnController.interruptTurn(deps)
    const doubleEmpty = turnController.interruptTurn(deps)

    expect(doubleEmpty).toBe(ctrlC)
    expect(request).toHaveBeenCalledTimes(1)

    rpc.resolve({ running: true, status: 'stopping' })
    await ctrlC
    expect(getUiState()).toMatchObject({ busy: true, status: 'stopping…' })
  })

  it('waits for authoritative interrupted completion after the Stop ack', async () => {
    const appended: Msg[] = []
    const request = vi.fn(async () => ({ quiesced: true, running: false, status: 'stopped' as const }))
    const onEvent = createGatewayEventHandler(buildEventContext(appended))

    await turnController.interruptTurn(stopDeps(request, appended))
    expect(getUiState()).toMatchObject({ busy: true, status: 'stopping…' })
    expect(appended).toEqual([])

    onEvent({
      payload: { status: 'interrupted', text: 'Stopped before completion.' },
      session_id: 'session-1',
      type: 'message.complete'
    } as any)

    expect(appended).toEqual([
      { role: 'assistant', status: 'interrupted', text: 'Stopped before completion.' }
    ])
    expect(getUiState()).toMatchObject({ busy: false, status: 'interrupted' })
  })

  it('preserves a successful terminal frame that beats the Stop response', async () => {
    const rpc = deferred<SessionStopResponse>()
    const request = vi.fn(() => rpc.promise)
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildEventContext(appended))

    const stopping = turnController.interruptTurn(stopDeps(request, appended))

    onEvent({
      payload: { status: 'complete', text: 'The operation completed first.' },
      session_id: 'session-1',
      type: 'message.complete'
    } as any)

    expect(appended).toEqual([
      { role: 'assistant', status: 'complete', text: 'The operation completed first.' }
    ])
    expect(getUiState()).toMatchObject({ busy: false, status: 'ready' })

    rpc.resolve({ running: true, status: 'stopping' })
    await stopping

    expect(appended).toHaveLength(1)
    expect(getUiState()).toMatchObject({ busy: false, status: 'ready' })
  })

  it('keeps running and surfaces a Stop RPC failure without losing retry', async () => {
    const request = vi
      .fn()
      .mockRejectedValueOnce(new Error('gateway unavailable'))
      .mockResolvedValueOnce({ running: true, status: 'finishing' })

    const sys = vi.fn()
    const deps = stopDeps(request, [], sys)

    await turnController.interruptTurn(deps)

    expect(sys).toHaveBeenCalledWith('stop failed: gateway unavailable')
    expect(getUiState()).toMatchObject({ busy: true, status: 'running…' })

    turnController.recordMessageDelta({ text: 'continued after failed Stop' })
    expect(turnController.bufRef).toBe('continued after failed Stop')

    await turnController.interruptTurn(deps)
    expect(request).toHaveBeenCalledTimes(2)
    expect(getUiState()).toMatchObject({ busy: true, status: 'finishing…' })
  })

  it('does not let late progress relabel a pending Stop', async () => {
    const rpc = deferred<SessionStopResponse>()
    const request = vi.fn(() => rpc.promise)
    const onEvent = createGatewayEventHandler(buildEventContext([]))
    const stopping = turnController.interruptTurn(stopDeps(request))

    onEvent({
      payload: { kind: 'status', text: 'Applying one more change…' },
      session_id: 'session-1',
      type: 'status.update'
    } as any)
    onEvent({
      payload: { text: 'Still thinking' },
      session_id: 'session-1',
      type: 'thinking.delta'
    } as any)

    expect(getUiState()).toMatchObject({ busy: true, status: 'stopping…' })

    rpc.resolve({ running: true, status: 'stopping' })
    await stopping
  })
})
