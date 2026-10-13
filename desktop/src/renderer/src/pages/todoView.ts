import type { Todo } from "../types";

type Task = Pick<Todo, "status" | "due_on" | "due_time" | "timezone">;
export type TodoView = "all" | "upcoming" | "overdue" | "incomplete" | "completed";
export type TodoGroup = "overdue" | "today" | "upcoming" | "later" | "noDate" | "cancelled" | "completed";

const formatters = new Map<string, Intl.DateTimeFormat>();
const clockInZone = (now: Date, zone: string) => {
  let formatter = formatters.get(zone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
    });
    formatters.set(zone, formatter);
  }
  const parts = Object.fromEntries(formatter.formatToParts(now).map((part) => [part.type, part.value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}:${parts.second}` };
};
const weekAfter = (day: string) => {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 7);
  return date.toISOString().slice(0, 10);
};

export const isDone = (todo: Pick<Todo, "status">) =>
  todo.status === "completed" || todo.status === "cancelled";

export function isOverdue(todo: Task, now: Date): boolean {
  if (isDone(todo) || !todo.due_on) return false;
  const clock = clockInZone(now, todo.timezone);
  return todo.due_on < clock.day ||
    (todo.due_on === clock.day && !!todo.due_time && `${todo.due_time}:00` < clock.time);
}

export function matchesTodoView(todo: Task, view: TodoView, now: Date): boolean {
  if (view === "all") return true;
  if (view === "completed") return todo.status === "completed";
  if (view === "overdue") return isOverdue(todo, now);
  if (view === "incomplete") return !isDone(todo) && !isOverdue(todo, now);
  if (isDone(todo) || isOverdue(todo, now) || !todo.due_on) return false;
  const today = clockInZone(now, todo.timezone).day;
  return todo.due_on >= today && todo.due_on <= weekAfter(today);
}

export function todoGroup(todo: Task, day: string | null, now: Date,
  hasOverdueChild = false, view: TodoView = "all"): TodoGroup {
  if ((view === "all" || view === "overdue") && hasOverdueChild) return "overdue";
  if (todo.status === "completed") return "completed";
  if (todo.status === "cancelled") return "cancelled";
  if (isOverdue(todo, now) || hasOverdueChild) return "overdue";
  if (!day) return "noDate";
  const today = clockInZone(now, todo.timezone).day;
  if (day <= today) return "today";
  return day <= weekAfter(today) ? "upcoming" : "later";
}
