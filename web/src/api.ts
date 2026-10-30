// Types mirror app/api_models.py. Money and dates are strings, exactly as the server sent them.

export type PatientType = "self_pay" | "insured";
export type Level = "red" | "amber" | "grey";

export interface Sample {
  id: string;
  title: string;
  patient_type: PatientType;
  gfe_total: string | null;
  has_eob: boolean;
}

export interface Line {
  service_date: string | null;
  code: string;
  modifier: string | null;
  description: string;
  units: number;
  charge: string;
  status: "ok" | "corrected" | "needs_review";
  note: string | null;
  dose_value?: string | null;
  dose_unit?: string | null;
  code_class?: "hcpcs_level2" | "unknown_level2" | "cpt_shaped" | "missing" | null;
}

export interface EvidenceLine {
  line_number: number;
  service_date: string | null;
  code: string;
  modifier: string | null;
  description: string;
  units: number;
  charge: string;
  dose_value?: string | null;
  dose_unit?: string | null;
}

export interface Finding {
  check: "duplicate" | "dose" | "units" | "gfe" | "eob" | "drug_benchmark" | "code";
  level: Level;
  wording: string;
  codes: string[];
  line_numbers: number[];
  dollars_at_stake: string;
  billing_review: boolean;
  expected_units: number | null;
  mue_value: number | null;
  mai: number | null;
  multiple: string | null;
  code_status: "valid_no_rate" | "unknown" | "not_checked" | null;
  overage: string | null;
  deadline: string | null;
  judge_decision: "keep" | "downgrade" | null;
  judge_reason: string | null;
  evidence: {
    bill_lines: EvidenceLine[];
    rule: string;
    data_row: Record<string, string | number | boolean | null>;
    computed: Record<string, string | number | boolean | null>;
    difference: string | null;
    source_name: string;
    source_url: string | null;
  };
}

export interface Call {
  step: string;
  model: string;
  latency_ms: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  ok: boolean;
}

export interface LookupLink {
  kind: "billing" | "assistance";
  title: string;
  url: string;
}

/** Mirrors app/lookup.py HospitalLookup: the hospital contacts card. */
export interface Lookup {
  status: "found" | "nothing_found" | "unavailable";
  hospital_name: string;
  phone: string | null;
  address: string | null;
  links: LookupLink[];
  message: string;
  verify_note: string;
}

export interface Case {
  id: string;
  patient_type: PatientType;
  stage: "confirm" | "results";
  read_with: string | null;
  facility_name: string | null;
  bill_date: string | null;
  amount_due: string | null;
  gfe_total: string | null;
  eob: { billed: string; allowed: string; patient_responsibility: string } | null;
  eob_note: string | null;
  lines: Line[];
  results: Results | null;
  lookup: Lookup | null;
  calls: Call[];
}

export interface Results {
  findings: Finding[];
  dollars_at_stake: string;
  deadline: string | null;
  likely_error_count: number;
  total_charges: string;
  gfe_overage: string | null;
}

export interface Letter {
  kind: string;
  title: string;
  text: string;
  body_html: string;
  pdf_url: string;
}

export interface ConfirmBody {
  lines: Line[];
  bill_date: string | null;
  amount_due: string | null;
  gfe_total: string | null;
}

export class ApiError extends Error {}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError("Could not reach ClaimGuard. Check your connection and try again.");
  }
  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (response.status === 422) message = "Some of the details look wrong. Please check them.";
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(message);
  }
  return (await response.json()) as T;
}

export const api = {
  samples: () => request<Sample[]>("/api/samples"),
  createSample: (id: string) => request<Case>(`/api/cases/sample/${id}`, { method: "POST" }),
  createCase: (form: FormData) => request<Case>("/api/cases", { method: "POST", body: form }),
  getCase: (id: string) => request<Case>(`/api/cases/${id}`),
  confirm: (id: string, body: ConfirmBody) =>
    request<Case>(`/api/cases/${id}/lines`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  lookup: (id: string, hospitalName?: string) =>
    request<Case>(`/api/cases/${id}/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hospital_name: hospitalName ?? null }),
    }),
  letters: (id: string) => request<Letter[]>(`/api/cases/${id}/letters`, { method: "POST" }),
};
