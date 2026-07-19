/**
 * Human status-bar labels + Core/Advanced nav filtering (Phase 2).
 * Exported so TerminalLayout and tests share one lookup.
 */

export type NavLeaf = { key: string; label: string; /** Hidden until Advanced is open */ advanced?: boolean };
export type NavGroup = {
  id: string;
  label: string;
  icon: string;
  key?: string;
  /** Whole group lives under Advanced */ advanced?: boolean;
  children?: NavLeaf[];
};

/** e.g. "COMMAND CENTER" or "MARKETS · CHART" */
export function statusLabelForPage(pageKey: string, navModel: NavGroup[]): string {
  for (const group of navModel) {
    if (group.key === pageKey) {
      return group.label.toUpperCase();
    }
    const leaf = group.children?.find((c) => c.key === pageKey);
    if (leaf) {
      return `${group.label.toUpperCase()} · ${leaf.label.toUpperCase()}`;
    }
  }
  return pageKey.replace(/[_:]/g, " ").toUpperCase();
}

function groupOwnsPage(group: NavGroup, pageKey: string): boolean {
  if (group.key === pageKey) return true;
  return !!group.children?.some((c) => c.key === pageKey);
}

/**
 * Progressive disclosure: hide Advanced groups/leaves unless expanded,
 * but always keep the active page's group/leaf visible (deep-link safety).
 */
export function filterNavForDisplay(
  navModel: NavGroup[],
  showAdvanced: boolean,
  activePage: string,
): NavGroup[] {
  const out: NavGroup[] = [];
  for (const group of navModel) {
    const ownsActive = groupOwnsPage(group, activePage);
    if (group.advanced && !showAdvanced && !ownsActive) continue;

    if (!group.children) {
      out.push(group);
      continue;
    }

    const children = group.children.filter(
      (c) => !c.advanced || showAdvanced || c.key === activePage,
    );
    if (children.length === 0 && !group.key) continue;
    out.push({ ...group, children });
  }
  return out;
}
