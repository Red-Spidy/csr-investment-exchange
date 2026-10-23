import { describe, expect, it } from 'vitest'
import { plainReason } from './reasons'

describe('plainReason: why a project is left out, in the company\'s words', () => {
  it('says a flagged project is still with the reviewer', () => {
    expect(plainReason('Status is flagged; only approved projects can be matched.')).toBe('Not approved yet: it is with the reviewer.')
  })
  it('says a funded project is already funded', () => {
    expect(plainReason('Status is active; only approved projects can be matched.')).toBe('Already funded.')
    expect(plainReason('Status is matched; only approved projects can be matched.')).toBe('Already funded.')
  })
  it('names the company\'s states', () => {
    expect(plainReason('Bihar is not one of Rajasthan.')).toBe('Bihar is outside your states (Rajasthan).')
    expect(plainReason('Bihar is not one of Rajasthan or Gujarat.')).toBe('Bihar is outside your states (Rajasthan or Gujarat).')
  })
  it('names the company\'s goals', () => {
    expect(plainReason('No overlap with the target SDG (6).')).toBe('Serves none of your development goals (SDG 6).')
    expect(plainReason('No overlap with the target SDGs (4, 5).')).toBe('Serves none of your development goals (SDGs 4, 5).')
  })
  it('names the company\'s budget per project', () => {
    expect(plainReason('Asks for ₹42,00,000, outside the ₹5,00,000 to ₹30,00,000 range.'))
      .toBe('Asks for ₹42,00,000, outside your ₹5,00,000 to ₹30,00,000 per project.')
  })
  it('leaves any other reason as written', () => {
    expect(plainReason('Something new.')).toBe('Something new.')
  })
})
