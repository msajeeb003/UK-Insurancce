/* Demo data (wireframe sample) — lets the whole flow be exercised
   without uploads or API credits. Only loads onto an empty project. */

function buildDemoColumns() {
  const sv = (v, page, conf) => ({ value: v, page, conf: conf || 'high' });
  const mk = (id, name, debt, d) => ({
    id, name, manual: false, debt, fileName: name.replace(/ /g, '-') + '_quote.pdf', data: d,
  });
  return [
    mk('demo-a', 'Insurer A', 'Included', {
      annual_turnover: sv('£4,500,000', 2), premium_rate: sv('0.32%', 3),
      estimated_annual_premium_exc_ipt: sv('£14,400', 3), minimum_annual_premium: sv('£10,000', 3),
      credit_limit_charges: sv('Included', 4), indemnity: sv('90%', 5),
      excess: sv('£1,000', 5), excess_type: sv('Minimum Retention', 5),
      max_annual_liability: sv('£2,000,000', 6), discretionary_limit: sv('£25,000', 6),
      max_terms_of_payment: sv('90 days', 7), max_extension_period: sv('60 days', 7),
      additional_info: sv('No-claims bonus 10%', 8),
    }),
    mk('demo-b', 'Insurer B', 'Included', {
      annual_turnover: sv('£4,500,000', 1), premium_rate: sv('0.28%', 2),
      estimated_annual_premium_exc_ipt: sv('£12,600', 2), minimum_annual_premium: sv('£9,500', 2),
      credit_limit_charges: sv('£45 per limit', 3), indemnity: sv('90%', 3),
      excess: sv('£2,500', 4), excess_type: sv('Deductible', 4),
      max_annual_liability: sv('£1,500,000', 4), discretionary_limit: sv('£20,000', 5, 'uncertain'),
      max_terms_of_payment: sv('60 days', 5), max_extension_period: sv('30 days', 5),
      additional_info: sv(null, null, null),
    }),
    mk('demo-c', 'Insurer C', 'Outsourced', {
      annual_turnover: sv('£4,500,000', 2), premium_rate: sv('0.35%', 3),
      estimated_annual_premium_exc_ipt: sv('£15,750', 4), minimum_annual_premium: sv('£11,000', 4),
      credit_limit_charges: sv('Included', 5), indemnity: sv('85%', 6),
      excess: sv('£1,000', 6), excess_type: sv('First Loss', 6),
      max_annual_liability: sv('£2,500,000', 7), discretionary_limit: sv(null, null, null),
      max_terms_of_payment: sv('120 days', 8), max_extension_period: sv('60 days', 8),
      additional_info: sv('New buyer cover to £50k. Quote subject to satisfactory proposal form.', 9),
    }),
    { id: 'demo-m1', name: 'Insurer A — Option 2', manual: true, debt: '', data: {} },
  ];
}

export function loadDemoData(p) {
  p.columns = buildDemoColumns();
  p.recommended = 'demo-b';
  p.credit = [
    { id: 'demo-r1', buyer: 'Meridian Foods Ltd', reg: '04821990', req: '£250,000',
      offers: { 'demo-a': '£250,000', 'demo-b': '£200,000', 'demo-c': '£250,000' } },
    { id: 'demo-r2', buyer: 'Harbord Retail Group', reg: '07733120', req: '£120,000',
      offers: { 'demo-a': '£120,000', 'demo-b': '£120,000', 'demo-c': '£100,000' } },
    { id: 'demo-r3', buyer: 'Castle Logistics Ltd', reg: '09912004', req: '£80,000',
      offers: { 'demo-a': '£75,000', 'demo-c': '£80,000' } },
  ];
  p.files = [
    { id: 'demo-f1', name: 'Insurer-A_quote_2026.pdf', kind: 'quote', ext: 'PDF',
      status: 'extracted', meta: 'Insurer A · quote · 8 pages · demo data', colId: 'demo-a' },
    { id: 'demo-f2', name: 'Insurer-B_quote.pdf', kind: 'quote', ext: 'PDF',
      status: 'extracted', meta: 'Insurer B · quote (scanned) · 6 pages · 1 value to verify · demo data', colId: 'demo-b' },
    { id: 'demo-f3', name: 'Insurer-C_quote.pdf', kind: 'quote', ext: 'PDF',
      status: 'extracted', meta: 'Insurer C · quote · 9 pages · demo data', colId: 'demo-c' },
    { id: 'demo-f4', name: 'credit-limits_schedule.pdf', kind: 'limits', ext: 'PDF',
      status: 'extracted', meta: 'credit-limit schedule · 3 buyers · demo data' },
  ];
  if (!p.clientName) p.clientName = 'Aldgate Timber Ltd';
  if (!p.approached.length) p.approached = ['allianz', 'atradius', 'coface', 'tmhcc'];
}
