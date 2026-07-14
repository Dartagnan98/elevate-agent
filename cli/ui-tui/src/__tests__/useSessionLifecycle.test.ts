import { describe, expect, it } from 'vitest'

import { resumedSessionStatus } from '../app/useSessionLifecycle.js'

describe('resumedSessionStatus', () => {
  it('preserves waiting-for-input truth on resume', () => {
    expect(
      resumedSessionStatus([
        { role: 'user', text: 'Prepare the package' },
        {
          role: 'assistant',
          status: 'needs_input',
          text: 'Which province is the property in?'
        }
      ])
    ).toBe('waiting for your input')
  })

  it('preserves pending truth on resume', () => {
    expect(resumedSessionStatus([{ role: 'assistant', status: 'pending', text: 'Still running' }])).toBe(
      'work still pending'
    )
  })
})
