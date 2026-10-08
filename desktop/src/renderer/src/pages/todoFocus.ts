import type { Todo } from "../types";

/** The path is rebuilt from current rows so moves and renames appear immediately. */
export function todoPath(id: string, byId: Map<string, Todo>): Todo[] {
  const path: Todo[] = [];
  const visited = new Set<string>();
  let current = byId.get(id);
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    path.unshift(current);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return path;
}

/** Keep the closest surviving ancestor when a focused task was deleted. */
export function survivingFocus(
  focusedId: string,
  previousPath: string[],
  byId: Map<string, Todo>,
): string | null {
  if (byId.has(focusedId)) return focusedId;
  return [...previousPath].reverse().find((id) => byId.has(id)) || null;
}

/** Keep the start and destination visible, placing intermediate nodes in a menu. */
export function breadcrumbParts<T>(items: T[], compact: boolean): { visible: T[]; hidden: T[] } {
  const keepStart = compact ? 1 : 2;
  const keepEnd = compact ? 1 : 2;
  if (items.length <= keepStart + keepEnd) return { visible: items, hidden: [] };
  return {
    visible: [...items.slice(0, keepStart), ...items.slice(-keepEnd)],
    hidden: items.slice(keepStart, -keepEnd),
  };
}
