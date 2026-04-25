#!/usr/bin/env -S node --max-old-space-size=8192 --expose-gc
import { GatewayClient } from './gatewayClient.js'
import { setupGracefulExit } from './lib/gracefulExit.js'
import { formatBytes, type HeapDumpResult, performHeapDump } from './lib/memory.js'
import { type MemorySnapshot, startMemoryMonitor } from './lib/memoryMonitor.js'

if (!process.stdin.isTTY) {
  console.log('elevate-tui: no TTY')
  process.exit(0)
}

const gw = new GatewayClient()

gw.start()

const dumpNotice = (snap: MemorySnapshot, dump: HeapDumpResult | null) =>
  `elevate-tui: ${snap.level} memory (${formatBytes(snap.heapUsed)}) — auto heap dump → ${dump?.heapPath ?? '(failed)'}\n`

setupGracefulExit({
  cleanups: [() => gw.kill()],
  onError: (scope, err) => {
    const message = err instanceof Error ? `${err.name}: ${err.message}` : String(err)

    process.stderr.write(`elevate-tui ${scope}: ${message.slice(0, 2000)}\n`)
  },
  onSignal: signal => process.stderr.write(`elevate-tui: received ${signal}\n`)
})

const stopMemoryMonitor = startMemoryMonitor({
  onCritical: (snap, dump) => {
    process.stderr.write(dumpNotice(snap, dump))
    process.stderr.write('elevate-tui: exiting to avoid OOM; restart to recover\n')
    process.exit(137)
  },
  onHigh: (snap, dump) => process.stderr.write(dumpNotice(snap, dump))
})

if (process.env.ELEVATE_HEAPDUMP_ON_START === '1') {
  void performHeapDump('manual')
}

process.on('beforeExit', () => stopMemoryMonitor())

const [{ render }, { App }] = await Promise.all([import('@elevate/ink'), import('./app.js')])

render(<App gw={gw} />, { exitOnCtrlC: false })
