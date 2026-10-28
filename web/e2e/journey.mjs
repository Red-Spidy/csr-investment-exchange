// The product, used as its users would: an NGO, the exchange reviewer and companies, each in
// their own browser, click through the real pages against the live API. It starts and ends with
// Reset demo data, so it assumes the seeded demo (db/seed.sql) and leaves it clean.
//
//   node e2e/journey.mjs                      against http://localhost:5173 (make api, make web)
//   WEB=http://127.0.0.1:4173 node e2e/journey.mjs
//
// Needs Google Chrome (or CHROME=/path/to/chrome). Screenshots go to demo-check/journey/.
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const WEB = process.env.WEB ?? 'http://localhost:5173'
const OUT = process.env.OUT ?? new URL('../../demo-check/journey/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })
const CHROME = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

const results = []
const problems = []          // console errors, page errors, failed requests
let shot = 0

async function step(name, fn) {
  const t0 = Date.now()
  try {
    await fn()
    results.push({ name, ok: true, ms: Date.now() - t0 })
    console.log(`  ✓ ${name} (${((Date.now() - t0) / 1000).toFixed(1)}s)`)
  } catch (e) {
    results.push({ name, ok: false, err: String(e.message ?? e).split('\n')[0] })
    console.log(`  ✗ ${name}\n      ${String(e.message ?? e).split('\n').slice(0, 3).join('\n      ')}`)
  }
}

const browser = await chromium.launch({ executablePath: CHROME, headless: true })


async function party(label, viewport = { width: 1440, height: 1000 }) {
  const ctx = await browser.newContext({ viewport })
  const page = await ctx.newPage()
  page.setDefaultTimeout(30_000)
  page.on('console', m => { if (m.type() === 'error') problems.push(`[${label}] console: ${m.text()} @ ${page.url()}`) })
  page.on('pageerror', e => problems.push(`[${label}] page error: ${e.message} @ ${page.url()}`))
  page.on('response', r => { if (r.status() >= 500) problems.push(`[${label}] HTTP ${r.status()} ${r.url()}`) })
  page.snap = async name => page.screenshot({ path: `${OUT}${String(++shot).padStart(2, '0')}-${label}-${name}.png`, fullPage: true })
  return page
}

const see = (page, text, opts = {}) => page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', ...opts })
const absent = async (page, text) => {
  if (await page.getByText(text, { exact: false }).count()) throw new Error(`"${text}" should not be on ${page.url()}`)
}
const receipt = async (page, title, ok = true) => {
  const r = page.locator('aside.receipt')
  await r.waitFor({ timeout: 120_000 })
  const got = await r.locator('h3').innerText()
  const isOk = (await r.getAttribute('data-ok')) === 'true'
  if (!got.includes(title) || isOk !== ok) throw new Error(`receipt "${got}" ok=${isOk}; wanted "${title}" ok=${ok}: ${await r.innerText()}`)
  return r.innerText()
}

// ------------------------------------------------------------------ the parties
const ngo = await party('ngo')          // Gramin Shiksha Trust
const review = await party('review')
const company = await party('company')  // Kalpataru Motors
const ngo2 = await party('ngo2')        // Arogya Health Mission

console.log('\nStart from a clean demo')
await step('reviewer resets the demo data from the console', async () => {
  await review.goto(`${WEB}/review`)
  await review.getByRole('button', { name: 'Reset demo data' }).click()
  await review.getByRole('button', { name: 'Reset', exact: true }).click()
  await review.getByRole('button', { name: 'Reset demo data' }).waitFor({ timeout: 180_000 })
  await see(review, 'Proposals to decide')
  await review.snap('queue-after-reset')
})

console.log('\nSign in')
await step('sign-in page offers the three accounts', async () => {
  await ngo.goto(WEB)
  await see(ngo, 'Sign in')
  for (const t of ['NGO', 'Company CSR team', 'Exchange reviewer']) await see(ngo, t)
  await ngo.snap('signin')
})
await step('an NGO signs in by choosing its organisation', async () => {
  await ngo.selectOption('#si-ngo', { label: 'Gramin Shiksha Trust' })
  await ngo.locator('form.account').first().getByRole('button', { name: 'Continue' }).click()
  await ngo.waitForURL(/\/ngo\/2$/)
  await see(ngo, 'My projects'); await see(ngo, 'Gramin Shiksha Trust')
  const title = await ngo.title()
  if (!title.startsWith('Gramin Shiksha Trust')) throw new Error(`tab title is "${title}"`)
})
await step('a company signs in', async () => {
  await company.goto(WEB)
  await company.selectOption('#si-company', { label: 'Kalpataru Motors Ltd' })
  await company.locator('form.account').nth(1).getByRole('button', { name: 'Continue' }).click()
  await company.waitForURL(/\/company\/2$/)
  await see(company, 'Overview'); await see(company, 'Kalpataru Motors')
})
await step('unknown accounts are sent back to sign in', async () => {
  const p = await party('stray')
  await p.goto(`${WEB}/ngo/999`); await p.waitForURL(`${WEB}/`)
  await p.goto(`${WEB}/company/abc`); await p.waitForURL(`${WEB}/`)
  await p.goto(`${WEB}/nowhere`); await p.waitForURL(`${WEB}/`)
  await p.context().close()
})

console.log('\nAn NGO submits a proposal')
await step('the form refuses a proposal that is too short', async () => {
  await ngo.getByRole('link', { name: 'New proposal' }).first().click()
  await ngo.waitForURL(/\/ngo\/2\/new$/)
  await ngo.fill('#sp-title', 'Too short')
  await ngo.fill('#sp-amount', '100000')
  await ngo.fill('#sp-text', 'We will help.')
  await ngo.getByRole('button', { name: 'Submit proposal' }).click()
  await ngo.waitForTimeout(500)
  if (!ngo.url().endsWith('/new')) throw new Error('submitted an invalid proposal')
  const valid = await ngo.locator('#sp-text').evaluate(el => el.validity.valid)
  if (valid) throw new Error('short text counted as valid')
})
let newProject = null
await step('the sample proposal is submitted, scored and graded in seconds', async () => {
  await ngo.getByRole('button', { name: 'Fill in a sample proposal' }).click()
  await ngo.snap('new-proposal-filled')
  const invalid = await ngo.evaluate(() => [...document.querySelectorAll('form :invalid')].map(e => `${e.id}: ${e.validationMessage}`))
  if (invalid.length) throw new Error(`the form blocks the sample: ${invalid.join('; ')}`)
  const t0 = Date.now()
  await ngo.getByRole('button', { name: 'Submit proposal' }).click()
  await ngo.waitForURL(/\/ngo\/2\/projects\/\d+$/, { timeout: 120_000 })
  newProject = Number(ngo.url().split('/').pop())
  await see(ngo, 'After-school science clubs for girls, Gaya')
  await see(ngo, 'What the reader picked out')
  console.log(`      scored in ${((Date.now() - t0) / 1000).toFixed(1)}s, project ${newProject}`)
  await ngo.snap('new-project')
})
await step('the NGO sees its result and grade, not the fraud screen', async () => {
  const side = await ngo.locator('.side-card').first().innerText()
  if (!/Approved|In review/.test(side)) throw new Error(`side card: ${side}`)
  await see(ngo, 'Expected impact')
  await absent(ngo, 'Spending check'); await absent(ngo, 'Overall score'); await absent(ngo, 'Anomal')
})
await step('the new proposal is listed under My projects', async () => {
  await ngo.getByRole('link', { name: 'My projects' }).first().click()
  await see(ngo, 'After-school science clubs for girls, Gaya')
  await ngo.snap('my-projects')
})
await step("an NGO cannot open another NGO's project", async () => {
  await ngo.goto(`${WEB}/ngo/2/projects/8`)
  await ngo.waitForTimeout(1500)
  const text = await ngo.locator('main').innerText()
  if (text.includes('Sanitation block construction')) throw new Error('NGO 2 can read Jal Seva Samiti\'s project 8')
})

await step('a missing project says so, instead of blaming the server', async () => {
  for (const path of ['/ngo/2/projects/999', '/review/projects/999', '/company/2/projects/abc']) {
    await ngo.goto(WEB + path)
    await see(ngo, 'Project not found')
    await absent(ngo, 'Cannot reach the server')
  }
})

console.log('\nThe reviewer works the queue')
await step('the queue lists the held-back proposals with a reason each', async () => {
  await review.goto(`${WEB}/review`)
  await see(review, 'Sanitation block construction')
  await see(review, 'Maternal health outreach')
  await see(review, 'Unusual spending history')
})
await step('the flagged sanitation project shows why: anomalous spending', async () => {
  await review.getByRole('link', { name: 'Sanitation block construction' }).first().click()
  await see(review, 'Why it is in review')
  await see(review, 'Spending check')
  await see(review, 'Round-number invoices')
  await see(review, 'Your decision')
  await review.snap('sanitation')
})
await step('the reviewer approves Maternal health outreach with a note', async () => {
  await review.goto(`${WEB}/review`)
  await review.getByRole('link', { name: /Maternal health outreach/ }).first().click()
  await review.fill('#review-note', 'baseline confirmed with the district office')
  await review.getByRole('button', { name: 'Approve' }).click()
  await receipt(review, 'Project approved')
  await see(review, 'Companies can now find and fund this project')
  await see(review, 'Why the scoring held it back')
  await see(review, 'A reviewer checked it and approved it')
  await absent(review, 'Why it is in review')
  await review.snap('approved')
})
await step('a decided project leaves the queue', async () => {
  await review.goto(`${WEB}/review`)
  await see(review, 'Proposals to decide')
  const table = review.locator('section:has(h2#decide)')
  await table.locator('tbody tr').first().waitFor()
  if (await table.getByText('Maternal health outreach').count()) throw new Error('still in queue')
})

await step('the reviewer rejects a proposal and its NGO is told', async () => {
  await review.goto(`${WEB}/review/projects/5`)
  await review.fill('#review-note', 'reforestation plan has no survival-rate target')
  await review.getByRole('button', { name: 'Reject' }).click()
  await receipt(review, 'Project rejected')
  const prakriti = await party('prakriti')
  await prakriti.goto(`${WEB}/ngo/5/projects/5`)
  await see(prakriti, 'The reviewer declined this proposal')
  await prakriti.context().close()
})

console.log('\nThe company funds it')
let committed = 0
await step('Find projects ranks the newly approved project', async () => {
  await company.reload()
  await company.getByRole('link', { name: 'Find projects' }).first().click()
  await see(company, 'Your criteria')
  await see(company, 'Maternal health outreach')
  await see(company, 'Not eligible')
  await see(company, 'Not approved yet: it is with the reviewer')
  await absent(company, 'Status is ')
  await company.snap('find')
})
await step('the company commits the requested amount in one step', async () => {
  const card = company.locator('li.match', { hasText: 'Maternal health outreach' })
  await card.getByRole('button', { name: 'Fund this project' }).click()
  await card.getByText('Each phase is paid only after its milestone is verified').waitFor()
  const btn = card.getByRole('button', { name: /^Commit/ })
  committed = await btn.innerText()
  await btn.click()
  await receipt(company, 'committed to')
  await see(company, 'Each phase is paid to the NGO once its milestone is verified')
  await company.snap('committed')
})
await step('the overview and funding pages show the commitment', async () => {
  await company.getByRole('link', { name: 'Overview' }).click()
  await see(company, 'Your projects')
  await see(company, 'Maternal health outreach')
  await company.getByRole('link', { name: 'Funding', exact: true }).click()
  // The heading itself: a looser text match also finds 'recorded in the ledger' in a folded form.
  await company.getByRole('heading', { name: 'Ledger' }).waitFor()
  await see(company, 'funds locked on match confirmation')
  await absent(company, 'Verify and release')
  await company.snap('funding')
})
await step('the same project cannot be funded twice', async () => {
  await company.getByRole('link', { name: 'Find projects' }).first().click()
  await see(company, 'Your criteria')
  const card = company.locator('li.match', { hasText: 'Maternal health outreach' })
  if (await card.count()) throw new Error('funded project is still offered')
})

console.log('\nThe NGO reports its first milestone')
await step('Arogya sees the evidence due under Needs you now', async () => {
  await ngo2.goto(`${WEB}/ngo/3`)
  await see(ngo2, 'Submit evidence for phase 1')
  await ngo2.snap('needs-you')
})
await step('the NGO submits evidence; no money moves yet', async () => {
  await ngo2.getByRole('link', { name: 'Submit evidence' }).first().click()
  await ngo2.waitForURL(/\/ngo\/3\/projects\/3/)
  const form = ngo2.locator('li.phase', { hasText: 'Phase 1' })
  const field = form.getByLabel('Result achieved')
  if (await field.inputValue() !== '') throw new Error(`the evidence field starts filled in with "${await field.inputValue()}"`)
  await field.fill('4')
  await form.getByRole('button', { name: 'Submit evidence' }).click()
  await receipt(ngo2, 'Evidence submitted')
  await form.getByText('Evidence submitted').waitFor()
  await see(ngo2, 'Waiting for the exchange reviewer')
  await absent(ngo2, 'Verify and release')
  await ngo2.snap('evidence-in')
})

console.log('\nThe reviewer verifies; the money moves')
await step('the evidence is waiting in the queue and verifying releases phase 1', async () => {
  await review.goto(`${WEB}/review`)
  const row = review.locator('tr', { hasText: 'Maternal health outreach' }).filter({ hasText: 'Phase 1' })
  await row.waitFor()
  await row.getByRole('button', { name: 'Verify' }).click()
  const text = await receipt(review, 'Phase 1 verified')
  if (!/release/i.test(text)) throw new Error(`receipt does not mention a release: ${text}`)
  await review.snap('verified')
})
await step('the company sees phase 1 released', async () => {
  await company.goto(`${WEB}/company/2/funding`)
  const phase1 = company.locator('section.commit', { hasText: 'Maternal health outreach' }).locator('li.phase', { hasText: 'Phase 1' })
  await phase1.getByText('Released').waitFor()
  await see(company, 'phase 1 released')
})

console.log('\nWhen a milestone fails')
await step('phase 2 evidence is submitted and the reviewer fails it', async () => {
  await ngo2.reload()
  const form = ngo2.locator('li.phase', { hasText: 'Phase 2' })
  await form.getByLabel('Result achieved').fill('4.2')
  await form.getByRole('button', { name: 'Submit evidence' }).click()
  await receipt(ngo2, 'Evidence submitted')
  await review.goto(`${WEB}/review/milestones`)
  const card = review.locator('section.commit', { hasText: 'Maternal health outreach' }).locator('li.phase', { hasText: 'Phase 2' })
  await card.getByRole('button', { name: 'Fail and hold' }).click()
  await receipt(review, 'Phase 2 failed')
  await card.getByText('Held').first().waitFor()
})
await step('the NGO is told its payment is held, not that it is in review', async () => {
  await ngo2.goto(`${WEB}/ngo/3`)
  await see(ngo2, 'Phase 2 failed verification')
  await see(ngo2, 'Payment held')
  await ngo2.goto(`${WEB}/ngo/3/projects/3`)
  await see(ngo2, 'its payment is held')
  await absent(ngo2, 'In review'); await absent(ngo2, 'before it can be funded')
  await review.goto(`${WEB}/review/projects`)
  const row = review.locator('tr', { hasText: 'Maternal health outreach' })
  await row.getByText('Payment held').waitFor()
})
await step('the company ends the commitment and gets the unreleased money back', async () => {
  await company.goto(`${WEB}/company/2/funding`)
  const block = company.locator('section.commit', { hasText: 'Maternal health outreach' })
  await block.getByText('Phase 2 failed verification').waitFor()
  await block.getByRole('button', { name: /^End and refund/ }).click()
  await block.getByRole('button', { name: 'End and refund', exact: true }).click()
  await receipt(company, 'Commitment ended')
  await block.getByText('Terminated').first().waitFor()
  await see(company, 'unreleased money returned to the company budget')
  await company.snap('ended')
})

await step('the company edits its funding criteria and the ranking uses them at once', async () => {
  await company.goto(`${WEB}/company/2/find`)
  await company.getByRole('button', { name: 'Edit criteria' }).click()
  await company.fill('#rb-text', 'Maternal and child health in rural districts, with a measurable target.')
  await company.getByLabel('Healthcare').check()
  await company.fill('#rb-min', '500000')
  await company.fill('#rb-max', '5000000')
  const invalid = await company.evaluate(() => [...document.querySelectorAll('form :invalid')].map(e => `${e.id}: ${e.validationMessage}`))
  if (invalid.length) throw new Error(`the form blocks round amounts: ${invalid.join('; ')}`)
  await company.getByRole('button', { name: 'Save criteria' }).click()
  await receipt(company, 'Criteria saved')
  await see(company, 'Maternal and child health in rural districts')
  await company.snap('criteria')
})

console.log('\nSafeguards')
await step('two sessions race to fund one project; exactly one wins', async () => {
  await review.goto(`${WEB}/review/safeguards`)
  await review.getByRole('button', { name: 'Race two sessions' }).click()
  await see(review, 'Exactly one commitment exists', { timeout: 60_000 })
})
await step('every rule-breaking attempt is refused by the database', async () => {
  const attempts = review.locator('li.attempt')
  const n = await attempts.count()
  for (let i = 0; i < n; i++) {
    const a = attempts.nth(i)
    await a.getByRole('button', { name: 'Try it' }).click()
    const answer = await a.locator('.attempt__answer').innerText({ timeout: 30_000 })
    if (!answer.startsWith('ERROR')) throw new Error(`${await a.locator('h3').innerText()}: ${answer}`)
  }
  await review.snap('safeguards')
})

console.log('\nImpact')
let monthsBefore = 0
await step('an NGO reports monthly progress and the company impact page recomputes', async () => {
  const meridian = await party('meridian')
  await meridian.goto(`${WEB}/company/1/impact`)
  await see(meridian, 'NGO leaderboard')
  const kpi = () => meridian.locator('.kpi', { hasText: 'Months reported' }).locator('.kpi__value').innerText()
  monthsBefore = Number(await kpi())
  await see(meridian, 'Progress against targets')
  const row = meridian.locator('tr', { hasText: 'Rural school attendance drive' })
  await row.getByText('+6.9 pp').waitFor()
  await row.getByText('86%').waitFor()
  const vidya = await party('vidya')
  await vidya.goto(`${WEB}/ngo/1/projects/1`)
  await see(vidya, 'Reported so far: +6.9 percentage points over 6 months, 86% of the +8 promised.')
  await see(vidya, 'Attendance rate gained this month (percentage points)')
  await vidya.fill('#progress', '1.4')
  await vidya.getByRole('button', { name: 'Report progress' }).click()
  await receipt(vidya, 'Monthly progress reported')
  await see(vidya, 'Reported so far: +8.3 percentage points over 7 months, 104% of the +8 promised.')
  await meridian.reload()
  await see(meridian, 'NGO leaderboard')
  const after = Number(await kpi())
  if (after !== monthsBefore + 1) throw new Error(`months reported ${monthsBefore} -> ${after}`)
  await meridian.locator('tr', { hasText: 'Rural school attendance drive' }).getByText('+8.3 pp').waitFor()
  await meridian.snap('impact')
  await meridian.context().close(); await vidya.context().close()
})

console.log('\nPhone width (390 x 844)')
await step('no page scrolls sideways on a phone', async () => {
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
  const p = await phone.newPage()
  const wide = []
  for (const path of ['/', '/ngo/2', '/ngo/2/new', `/ngo/3/projects/3`, '/company/2', '/company/2/find', '/company/2/funding',
    '/company/1/impact', '/review', '/review/projects', '/review/projects/8', '/review/milestones', '/review/safeguards']) {
    await p.goto(WEB + path); await p.waitForTimeout(1200)
    const w = await p.evaluate(() => document.documentElement.scrollWidth)
    if (w > 392) wide.push(`${path} is ${w}px wide`)
    await p.screenshot({ path: `${OUT}phone${path.replace(/\//g, '_') || '_signin'}.png`, fullPage: true })
  }
  await phone.close()
  if (wide.length) throw new Error(wide.join('; '))
})

console.log('\nLeave a clean demo')
await step('reset rebuilds and rescores', async () => {
  await review.goto(`${WEB}/review`)
  await review.getByRole('button', { name: 'Reset demo data' }).click()
  await review.getByRole('button', { name: 'Reset', exact: true }).click()
  await review.getByRole('button', { name: 'Reset demo data' }).waitFor({ timeout: 180_000 })
})

await browser.close()
const failed = results.filter(r => !r.ok)
console.log(`\n${results.length - failed.length} of ${results.length} steps passed.`)
if (problems.length) console.log(`\nBrowser problems (${problems.length}):\n  ` + [...new Set(problems)].join('\n  '))
else console.log('No console errors, page errors or server errors.')
process.exit(failed.length ? 1 : 0)
