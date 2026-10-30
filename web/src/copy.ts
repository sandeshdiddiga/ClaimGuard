// Plain-language copy around each finding. The finding's own sentence comes from the server (docs/SPEC.md
// section 5); this file only adds "why it matters" and "what to do". No amounts are computed here.

import type { Finding, Level } from "./api";

export const LEVEL_WORD: Record<Level, string> = {
  red: "Likely error",
  amber: "Worth asking about",
  grey: "For context",
};

export const CHECK_TITLE: Record<Finding["check"], string> = {
  duplicate: "Charged twice",
  dose: "Dose and billed units",
  units: "More units than Medicare's daily limit",
  gfe: "Over your Good Faith Estimate",
  eob: "More than your insurer says you owe",
  drug_benchmark: "Compared with Medicare's drug price",
  code: "About this code",
};

interface Advice {
  why: string;
  todo: string;
}

export function advice(f: Finding): Advice {
  switch (f.check) {
    case "duplicate":
      return {
        why: "The same item, on the same day, in the same amount, appears more than once. You may be paying for it twice.",
        todo: "Ask the billing office to remove the repeat or explain it. The correction letter lists both lines.",
      };
    case "dose":
      if (f.level === "amber")
        return {
          why: "The bill gives the dose in a different measure from the one this drug is billed in, so the units can't be checked from the bill alone.",
          todo: "Ask the billing office how they turned the dose into billed units.",
        };
      if (f.billing_review)
        return {
          why: "Drugs are billed in fixed amounts per unit, and this line doesn't add up. Your insurer's EOB, not this line, sets what you owe.",
          todo: "Ask for a billing review so the claim your insurer pays is correct.",
        };
      return {
        why: "Drugs are billed in fixed amounts per unit. Counting the dose itself as the units multiplies the charge.",
        todo: "Ask for a corrected bill. The correction letter shows the arithmetic.",
      };
    case "units":
      if (f.billing_review)
        return {
          why: "Medicare sets a most-units-per-day limit for this item (a Medically Unlikely Edit, or MUE). Private insurers don't have to follow it, but it is a fair reason to ask.",
          todo: "Ask for a billing review.",
        };
      if (f.level === "amber")
        return {
          why: "Medicare's daily limit for this item (a Medically Unlikely Edit, or MUE) allows more when a clinician documents why.",
          todo: "Ask the billing office what the extra units were for.",
        };
      return {
        why: "Medicare sets a most-units-per-day limit for this item (a Medically Unlikely Edit, or MUE), with no exceptions. Billing more is very unlikely to be right.",
        todo: "Ask for a corrected bill. The correction letter lists the line.",
      };
    case "gfe":
      return {
        why: "If you're paying yourself and the bill is $400 or more over the Good Faith Estimate you were given, you can start a federal billing dispute.",
        todo: "Use the dispute summary letter, and start the dispute before the deadline.",
      };
    case "eob":
      return {
        why: "Your insurer's Explanation of Benefits (EOB) says what you owe after the plan has paid. The hospital is asking for more.",
        todo: "Send the rebilling letter with a copy of your EOB.",
      };
    case "drug_benchmark":
      return {
        why: "Hospitals usually charge more than Medicare pays. This is not an error.",
        todo: "If you're paying yourself, it can help when you ask for a discount.",
      };
    case "code":
      if (f.code_status === "not_checked")
        return {
          why: "This looks like a CPT code. CPT codes belong to the American Medical Association, and ClaimGuard uses only public CMS data, so it can't look this code up.",
          todo: "The other checks on this line still ran. Ask the billing office about it if anything is unclear.",
        };
      if (f.code_status === "unknown")
        return {
          why: "This code isn't in Medicare's current list of HCPCS codes (the codes hospitals use for supplies, drugs and some services), so we couldn't check it.",
          todo: "Check it against your bill, and ask the billing office what it is.",
        };
      return {
        why: "This is a valid HCPCS code (Medicare's code for this service). There is no public Medicare price for it in the data we use.",
        todo: "Nothing to do.",
      };
  }
}

// Model IDs as people should read them. The raw ID is shown small beside it.
export const MODEL_NAME: Record<string, string> = {
  "nvidia/Nemotron-3.5-Super-VL": "Nemotron 3.5 Super VL",
  "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": "Nemotron 3 Nano",
  "nvidia/Nemotron-3-Ultra-550b-a55b": "Nemotron 3 Ultra",
  "nvidia/nemotron-3-super-120b-a12b": "Nemotron 3 Super",
  tavily: "Tavily web search",
};

export const STEP_NAME: Record<string, string> = {
  read_document: "Read the bill",
  clean_codes: "Tidy the codes and read the doses",
  judge_amber: "Second look at a line worth asking about",
  explain: "Explain a finding",
  draft_letter: "Write a letter's opening paragraph",
  search_web: "Search the web for the hospital",
  pick_links: "Pick contact details from the search results",
};

export const DATA_LABEL: Record<string, string> = {
  code: "Code",
  hcpcs_description: "CMS description",
  short_description: "CMS short description",
  long_description: "CMS description",
  termination_date: "Code ended",
  dosage: "Billed per",
  payment_limit: "Medicare limit per unit ($)",
  mue_value: "Daily limit (units)",
  mai: "How strict the limit is (1 and 2 are firm, 3 allows clinical judgment)",
  rationale: "CMS reason",
  facility_total: "Billed ($)",
  good_faith_estimate: "Your estimate ($)",
  threshold: "Dispute threshold ($)",
  bill_date: "Bill date",
  window_days: "Days to dispute",
  deadline: "Deadline",
  eob_billed: "EOB: billed ($)",
  eob_allowed: "EOB: allowed ($)",
  eob_patient_responsibility: "EOB: you owe ($)",
  bill_balance_due: "Bill: balance due ($)",
  service_date: "Date",
  units: "Units",
  modifier: "Modifier",
  occurrences: "Times on the bill",
  stated_dose: "Dose on the bill",
  dose_per_unit: "Billed per",
  expected_units: "Units for that dose",
  billed_units: "Units billed",
  excess_units: "Extra units",
  unit_charge: "Charge per unit ($)",
  counted: "Amount in question ($)",
  limit: "Daily limit (units)",
  repeats: "Extra copies",
  overage: "Over the estimate ($)",
  difference: "Difference ($)",
  charge_per_unit: "Charge per unit ($)",
  multiple: "Times Medicare's limit",
  code_class: "Kind of code",
  in_current_list: "In CMS's current list",
  has_payment_limit: "Has a Medicare drug price",
};
