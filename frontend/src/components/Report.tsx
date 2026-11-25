import type { Field, Report as ReportData, Status } from "../api";
import { CHECK_LABELS, FIELD_LABELS, formatValue } from "../labels";

export function Report({ report }: { report: ReportData }) {
  return (
    <>
      <Verdict report={report} />
      <Checks report={report} />
      <section className="fields-grid">
        <Fields title="Contract" fields={report.contract} textMethod={report.text_method.contract} />
        <Fields title="Invoice" fields={report.invoice} textMethod={report.text_method.invoice} />
      </section>
    </>
  );
}

const VERDICT_CLASS = { "ISSUES FOUND": "fail", "NEEDS REVIEW": "review", "ALL CHECKS PASSED": "pass" };

function Verdict({ report }: { report: ReportData }) {
  const { counts } = report;
  const cost = report.cost_usd === null ? "unknown cost" : `$${report.cost_usd.toFixed(3)}`;
  return (
    <section className={`card verdict ${VERDICT_CLASS[report.verdict]}`}>
      <div>
        <h2>{report.verdict}</h2>
        <p>
          {counts.FAIL} failed · {counts.REVIEW} need review · {counts.PASS} passed
        </p>
      </div>
      <p className="meta">
        {report.model} · {cost} · {report.seconds}s
      </p>
    </section>
  );
}

function Checks({ report }: { report: ReportData }) {
  const expected = report.expected?.checks;
  const mismatches = expected ? report.checks.filter((c) => expected[c.name] !== c.status).length : 0;
  return (
    <section className="card">
      <div className="card-head">
        <h3>Checks</h3>
        {expected && (
          <span className={`expected-summary ${mismatches ? "bad" : "good"}`}>
            {mismatches === 0
              ? "✓ Matches the expected result"
              : `✗ ${mismatches} check${mismatches > 1 ? "s differ" : " differs"} from the expected result`}
          </span>
        )}
      </div>
      <div className="table-wrap">
        <table className="checks">
          <thead>
            <tr>
              <th>Result</th>
              <th>Check</th>
              <th>Details</th>
              {expected && <th>Expected</th>}
            </tr>
          </thead>
          <tbody>
            {report.checks.map((c) => (
              <tr key={c.name}>
                <td><Badge status={c.status} /></td>
                <td className="check-name">{CHECK_LABELS[c.name] ?? c.name}</td>
                <td>{c.message}</td>
                {expected && (
                  <td className={expected[c.name] === c.status ? "match" : "mismatch"}>
                    {expected[c.name] === c.status ? "✓" : `✗ ${expected[c.name]}`}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Badge({ status }: { status: Status }) {
  return <span className={`badge ${status.toLowerCase()}`}>{status}</span>;
}

const SCAN_NOTES = {
  pdf_text: null,
  ocr: "Scanned document: the quotes were checked against text read with OCR.",
  none: "Scanned document: OCR isn't installed on the server, so the quotes couldn't be checked.",
};

function Fields(props: { title: string; fields: Record<string, Field>; textMethod: keyof typeof SCAN_NOTES }) {
  const { title, fields, textMethod } = props;
  const scanNote = SCAN_NOTES[textMethod];
  return (
    <section className="card">
      <h3>{title}: extracted fields</h3>
      <p className="hint">Each value with the exact text it was read from in the PDF.</p>
      {scanNote && <p className={`scan-note ${textMethod}`}>{scanNote}</p>}
      <dl className="fields">
        {Object.entries(fields).map(([name, f]) => (
          <div key={name} className="field-row">
            <dt>{FIELD_LABELS[name] ?? name}</dt>
            <dd>
              <span className="value">{formatValue(f.value)}</span>
              {f.source && (
                <span className={`source ${f.verified ? "" : "unverified"}`}>
                  “{f.source}”{!f.verified && " · not found in the document"}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
