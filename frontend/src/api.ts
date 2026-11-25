// Types and calls for the Python API (checker/api.py).

export type Status = "PASS" | "FAIL" | "REVIEW";

export interface Field {
  value: string | number | null;
  source: string | null;
  verified: boolean; // false = the source quote was not found in the PDF
}

export interface CheckResult {
  name: string;
  status: Status;
  message: string;
}

export interface Report {
  verdict: "ISSUES FOUND" | "NEEDS REVIEW" | "ALL CHECKS PASSED";
  counts: Record<Status, number>;
  checks: CheckResult[];
  contract: Record<string, Field>;
  invoice: Record<string, Field>;
  model: string;
  cost_usd: number | null;
  seconds: number;
  // How each document's text was read for the source check. A scan has no
  // text layer: "ocr" = read with OCR, "none" = OCR not installed on the server.
  text_method: Record<"contract" | "invoice", "pdf_text" | "ocr" | "none">;
  // Only present when a test case was checked:
  expected?: { description: string; checks: Record<string, Status> };
}

export interface TestCase {
  id: string;
  description: string;
  commodity: string;
  expected_issues: number;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // the body wasn't JSON; keep the status text
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const listCases = () => request<TestCase[]>("/api/cases");

export const checkCase = (caseId: string) =>
  request<Report>(`/api/cases/${caseId}/check`, { method: "POST" });

export function checkUpload(contract: File, invoice: File) {
  const form = new FormData();
  form.append("contract", contract);
  form.append("invoice", invoice);
  return request<Report>("/api/check", { method: "POST", body: form });
}

export const casePdfUrl = (caseId: string, doc: "contract" | "invoice") =>
  `/api/cases/${caseId}/${doc}.pdf`;
