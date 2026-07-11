/**
 * PlannedModule — honest scaffold for a Markets view whose data source isn't
 * wired yet. Shows the intended layout and what it needs, rather than faking data.
 */
import React from "react";

export default function PlannedModule({ title, blurb, needs, columns }: {
  title: string;
  blurb: string;
  needs: string;
  columns: string[];
}) {
  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">{title}</span>
        <span style={{
          fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--amber)",
          border: "1px solid var(--amber)", padding: "2px 6px", borderRadius: 2,
        }}>
          data source pending
        </span>
      </div>

      <p style={{ fontSize: 13, color: "var(--ink-dim)", maxWidth: 620, lineHeight: 1.6 }}>{blurb}</p>

      <table className="t-table" style={{ marginTop: 12, opacity: 0.5 }}>
        <thead>
          <tr>{columns.map(c => <th key={c} style={{ textAlign: "left" }}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {[0, 1, 2].map(i => (
            <tr key={i}>
              {columns.map(c => (
                <td key={c} className="mono" style={{ color: "var(--ink-faint)" }}>—</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{
        marginTop: 16, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)",
        borderLeft: "2px solid var(--line-dim)", paddingLeft: 10,
      }}>
        Needs: {needs}
      </div>
    </div>
  );
}
