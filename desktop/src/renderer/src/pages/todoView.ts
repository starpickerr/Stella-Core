import type { Todo } from "../types";

type Task = Pick<Todo, "status" | "due_on" | "due_time">;
export type TodoView = "all" | "upcoming" | "overdue" | "incomplete" | "completed";
export type TodoGroup = "overdue" | "today" | "upcoming" | "later" | "noDate" | "completed";

const dateKey = (value: Date) =>
  `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;

export const isDone = (todo: Pick<Todo, "status">) =>
  todo.status === "completed" || todo.status === "cancelled";

export function isOverdue(todo: Task, now: Date): boolean {
  if (isDone(todo) || !todo.due_on) return false;
  const today = dateKey(now);
  return todo.due_on < today ||
    (todo.due_on === today && !!todo.due_time && todo.due_time.slice(0, 5) <
      `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`);
}

export function matchesTodoView(todo: Task, view: TodoView, now: Date, soon: string): boolean {
  if (view === "all") return true;
  if (view === "completed") return todo.status === "completed";
  if (view === "overdue") return isOverdue(todo, now);
  if (view === "incomplete") return !isDone(todo) && !isOverdue(todo, now);
  return !isDone(todo) && !isOverdue(todo, now) && !!todo.due_on &&
    todo.due_on >= dateKey(now) && todo.due_on <= soon;
}

export function todoGroup(todo: Task, day: string | null, now: Date, soon: string,
  hasOverdueChild = false): TodoGroup {
  if (isDone(todo)) return "completed";
  if (isOverdue(todo, now) || hasOverdueChild) return "overdue";
  if (!day) return "noDate";
  const today = dateKey(now);
  if (day <= today) return "today";
  return day <= soon ? "upcoming" : "later";
}
