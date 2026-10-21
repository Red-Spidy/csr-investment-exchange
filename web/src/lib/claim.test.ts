import { describe, expect, it } from 'vitest'
import { promisedChange } from './claim'

describe('promisedChange: how much a proposal promises, in its own units', () => {
  it('is the gap between the stated baseline and target', () => {
    expect(promisedChange({ name: 'attendance_rate', unit: 'percentage_points', baseline: 61, target: 69 })).toBe(8)
  })
  it('is the size of a promised reduction', () => {
    expect(promisedChange({ name: 'waterborne_disease_incidence', unit: 'percent', baseline: 18, target: 12 })).toBe(6)
  })
  it('is the target itself for a metric that starts from nothing', () => {
    expect(promisedChange({ name: 'tree_cover', unit: 'hectares', baseline: null, target: 320 })).toBe(320)
  })
  it('is unknown when the reader found a target but no baseline', () => {
    expect(promisedChange({ name: 'attendance_rate', unit: 'percentage_points', baseline: null, target: 57 })).toBeNull()
  })
  it('is unknown when no target was stated', () => {
    expect(promisedChange(null)).toBeNull()
  })
})
