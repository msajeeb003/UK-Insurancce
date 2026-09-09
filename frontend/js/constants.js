/* Shared constants: field definitions, standing-list fallback, icons.
   The live insurer list is CONFIGURATION served by the backend
   (GET /insurers <- backend/config/insurers.json); the array here is only
   the fallback until that request resolves. */

export let INSURERS = [
  { id: 'allianz',  name: 'Allianz Trade',    debtIncl: true  },
  { id: 'atradius', name: 'Atradius',         debtIncl: true  },
  { id: 'coface',   name: 'Coface',           debtIncl: true  },
  { id: 'tmhcc',    name: 'Tokio Marine HCC', debtIncl: false },
  { id: 'qbe',      name: 'QBE',              debtIncl: false },
  { id: 'aig',      name: 'AIG',              debtIncl: false },
  { id: 'chubb',    name: 'Chubb',            debtIncl: false },
  { id: 'markel',   name: 'Markel',           debtIncl: false },
  { id: 'nexus',    name: 'Nexus',            debtIncl: false },
  { id: 'aviva',    name: 'Aviva',            debtIncl: false },
  { id: 'zurich',   name: 'Zurich',           debtIncl: false },
  { id: 'cartan',   name: 'Cartan',           debtIncl: false },
];

export function setInsurers(list) { INSURERS = list; }

/* Review grid rows. `key` matches the backend JSON where extracted;
   set:true rows are broker/rule-set (never extracted). */
export const FIELDS = [
  { key: 'annual_turnover', label: 'Turnover' },
  { key: 'type',     label: 'Type of Policy', tag: 'SET', note: 'Set by broker · overridable', set: true },
  { key: 'premium_rate', label: 'Premium Rate' },
  { key: 'estimated_annual_premium_exc_ipt', label: 'Estimated Annual Premium', note: 'Excl. IPT', confirm: 'premium' },
  { key: 'minimum_annual_premium', label: 'Minimum Annual Premium', note: 'Excl. IPT' },
  { key: 'credit_limit_charges', label: 'Credit Limit Charges', note: 'Excl. VAT' },
  { key: 'debt',     label: 'Debt Collection support', tag: 'RULE', note: 'Set by insurer rule', set: true },
  { key: 'indemnity', label: 'Indemnity', confirm: 'indemnity' },
  { key: 'excess',   label: 'Excess', confirm: 'excess' },
  { key: 'excess_type', label: 'Excess Type', note: 'Insurer’s own term' },
  { key: 'max_annual_liability', label: 'Max Annual Liability', confirm: 'maxLiability' },
  { key: 'discretionary_limit', label: 'Discretionary Limit' },
  { key: 'max_terms_of_payment', label: 'Max Terms of Payment' },
  { key: 'max_extension_period', label: 'Max Extension Period' },
  { key: 'additional_info', label: 'Additional Info', note: 'Free-format' },
];

export const CONFIRM_KEYS = ['premium', 'indemnity', 'excess', 'maxLiability'];

export const MINI_FIELDS = [
  ['premium_rate', 'Premium rate'], ['estimated_annual_premium_exc_ipt', 'Est. premium'],
  ['indemnity', 'Indemnity'], ['excess', 'Excess'], ['max_annual_liability', 'Max liability'],
];

export const POLICY_OPTIONS = ['Whole Turnover', 'Top-Up', 'Single Risk', 'Gap-Fill'];

export const STEPS = [
  ['setup', 'Setup'], ['upload', 'Upload'], ['review', 'Review'],
  ['limits', 'Credit limits'], ['recommend', 'Recommendation'], ['export', 'Generate'],
];

export const MAX_QUOTES = 6;

export const DOC_TYPE_LABELS = {
  insurer_quote: 'quote', credit_limit_schedule: 'credit-limit schedule',
  policy_document: 'policy document', other: 'document',
};

/* UI confirm-flag key -> backend field name (BRD 2.5 gate). */
export const CONFIRM_FIELD_MAP = {
  premium: 'estimated_annual_premium_exc_ipt',
  indemnity: 'indemnity',
  excess: 'excess',
  maxLiability: 'max_annual_liability',
};

export const ICON = {
  plus: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" style="margin-right:7px;vertical-align:-2px"><path d="M12 5v14M5 12h14"/></svg>',
  search: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>',
  upload: '<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V7m0 0l-3 3m3-3l3 3"/><path d="M20 16.5A3.8 3.8 0 0017.5 9.6 5.5 5.5 0 006.3 11 4 4 0 005 18.9"/></svg>',
  table: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M3 9.5h18M9 4.5v15"/></svg>',
  refresh: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 12a8.5 8.5 0 11-2.6-6.1M20.5 4v5h-5"/></svg>',
  download: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14"/></svg>',
};
