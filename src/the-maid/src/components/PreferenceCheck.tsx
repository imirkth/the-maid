// The Maid — preference check shown before the first tree build.
// Each choice is previewed on the user's own files, so they pick what they see.
import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  addAreasFromText, answer, initialAnswers, toPayload, toggleArea, toggleProtected,
  type TreeChoices, type TreePreferences,
} from "../lib/preferences";

interface Props {
  files: unknown[];
  directory: string;
  onDone: () => void;      // build the tree with the saved preferences
  onCancel: () => void;
}

export default function PreferenceCheck({ files, directory, onDone, onCancel }: Props) {
  const [choices, setChoices] = useState<TreeChoices | null>(null);
  const [prefs, setPrefs] = useState<TreePreferences>(initialAnswers(null));
  const [areaText, setAreaText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    invoke<TreeChoices>("get_tree_choices", { files, directory })
      .then((c) => { if (alive) { setChoices(c); setPrefs(initialAnswers(c)); } })
      .catch((e) => { if (alive) setError(String(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [files, directory]);

  const save = async () => {
    setSaving(true); setError("");
    try {
      const withTyped = { ...prefs, areas: addAreasFromText(prefs.areas, areaText) };
      await invoke("save_preferences", { preferences: toPayload(withTyped) });
      onDone();
    } catch (e) { setError(String(e)); setSaving(false); }
  };

  if (loading) {
    return <div className="pref-check"><p className="scan-summary">I’m looking at your files to prepare a few quick choices…</p></div>;
  }

  return (
    <div className="pref-check">
      <h3>How do you like your files?</h3>
      <p className="muted">A few quick choices, shown on your own files. I’ll remember them for every future scan.</p>
      {error && <div className="error">⚠️ {error}</div>}

      {choices?.questions.map((q) => (
        <div key={q.id} className="pref-question">
          <p className="pref-question-title">{q.question}</p>
          <div className="pref-options">
            {q.options.map((o) => {
              const selected = prefs[q.id] === o.value;
              return (
                <button key={o.value} type="button" className={`pref-option${selected ? " selected" : ""}`}
                  aria-pressed={selected} onClick={() => setPrefs((p) => answer(p, q, o.value))}>
                  <strong>{o.label}</strong>
                  <ul>{o.preview.map((line) => <li key={line}>{line}</li>)}</ul>
                </button>
              );
            })}
          </div>
        </div>
      ))}

      <div className="pref-question">
        <p className="pref-question-title">What are the main areas of your life on this computer? <span className="muted">(optional)</span></p>
        <div className="pref-chips">
          {[...new Set([...(choices?.suggested_areas ?? []), ...prefs.areas])].map((a) => {
            const on = prefs.areas.some((x) => x.toLowerCase() === a.toLowerCase());
            return (
              <button key={a} type="button" className={`pref-chip${on ? " selected" : ""}`} aria-pressed={on}
                onClick={() => setPrefs((p) => ({ ...p, areas: toggleArea(p.areas, a) }))}>{a}</button>
            );
          })}
        </div>
        <input type="text" placeholder="Add your own, e.g. Cryocare, Kids, Boat" value={areaText}
          onChange={(e) => setAreaText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { setPrefs((p) => ({ ...p, areas: addAreasFromText(p.areas, areaText) })); setAreaText(""); }
          }} />
      </div>

      {(choices?.protect_candidates.length ?? 0) > 0 && (
        <div className="pref-question">
          <p className="pref-question-title">Any of your folders I must never touch?</p>
          {choices!.protect_candidates.map((c) => (
            <label key={c.path} className="pref-protect">
              <input type="checkbox" checked={prefs.protected.includes(c.path)}
                onChange={() => setPrefs((p) => ({ ...p, protected: toggleProtected(p.protected, c.path) }))} />
              {c.name} <span className="muted">({c.files} files)</span>
            </label>
          ))}
        </div>
      )}

      <div className="pref-actions">
        <button className="primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Build my tree"}</button>
        <button className="secondary" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
    </div>
  );
}
