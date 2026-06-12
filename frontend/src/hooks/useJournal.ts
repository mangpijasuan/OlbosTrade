import { useState, useEffect } from "react";
import { api } from "../api/client";

export function useJournal() {
  const [entries, setEntries] = useState<any[]>([]);
  const [ruleBreachImpact, setRuleBreachImpact] = useState<any>(null);
  const [tagPerformance, setTagPerformance] = useState<any[]>([]);
  const [mistakes, setMistakes] = useState<any>({});
  const [loading, setLoading] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [e, rbi, tags, m] = await Promise.all([
        api.getJournalEntries() as any,
        api.getRuleBreachImpact() as any,
        api.getTagPerformance() as any,
        api.getMistakeFrequency() as any,
      ]);
      setEntries(e.entries ?? []);
      setRuleBreachImpact(rbi.impact ?? null);
      setTagPerformance(tags.tag_performance ?? []);
      setMistakes(m.mistakes ?? {});
    } finally { setLoading(false); }
  };

  const createEntry = async (data: object) => {
    await api.createJournalEntry(data);
    await loadAll();
  };

  useEffect(() => { loadAll(); }, []);
  return { entries, ruleBreachImpact, tagPerformance, mistakes, loading, createEntry, loadAll };
}
