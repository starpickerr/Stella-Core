import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  BellRing,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  CornerUpLeft,
  Flag,
  GripVertical,
  MoreHorizontal,
  Pencil,
  Plus,
  Repeat2,
  Search,
  Trash2,
  X,
} from "lucide-react";
import apiClient from "../api/client";
import { getLang } from "../i18n";
import EmbeddedAgent, { enqueueEmbeddedPreset, type PresetRequest } from "../components/EmbeddedAgent";
import type {
  Todo,
  TodoChecklistItem,
  TodoInput,
  UncertainReminder,
  NotificationRoute,
} from "../types";
import { breadcrumbParts, survivingFocus, todoPath } from "./todoFocus";
import { isDone, isOverdue, matchesTodoView, todoGroup, type TodoView } from "./todoView";

const pad = (value: number) => String(value).padStart(2, "0");
const dateKey = (value: Date) =>
  `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
const fromLocalTime = (value: string) =>
  value ? new Date(value).toISOString() : null;
const toLocalTime = (value: string | null) => {
  if (!value) return "";
  const date = new Date(value);
  return `${dateKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};
const tagsOf = (todo: Todo) => JSON.parse(todo.tags || "[]") as string[];
const checklistOf = (todo: Todo) =>
  JSON.parse(todo.checklist || "[]") as TodoChecklistItem[];
const taskKey = (todo: Todo) => todo.series_id || todo.id;
const taskDate = (todo: Todo) => todo.planned_on || todo.due_on;
const statusColors: Record<Todo["status"], string> = {
  todo: "text-content-tertiary",
  in_progress: "text-accent",
  waiting: "text-amber-500",
  blocked: "text-danger",
  completed: "text-accent",
  cancelled: "text-content-tertiary",
};

type Sort = "date" | "priority" | "manual";

const TodosPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const en = getLang() === "en";
  const copy = en
    ? {
        title: "Tasks",
        subtitle: "One place for what needs attention.",
        newTask: "New task",
        today: "Today",
        upcoming: "Due soon",
        all: "All tasks",
        incomplete: "Incomplete",
        completed: "Completed",
        cancelled: "Cancelled",
        search: "Search tasks",
        list: "List / project",
        allLists: "All lists",
        tags: "Tags",
        allTags: "All tags",
        flagged: "Flagged",
        allFlags: "Any flag",
        status: "Status",
        allStatuses: "Any status",
        sort: "Sort",
        dateSort: "Date",
        prioritySort: "Priority",
        manualSort: "Manual order",
        overdue: "Overdue",
        later: "Later",
        noDate: "No date",
        empty: "No tasks in this view",
        createHint: "What needs to be done?",
        advanced: "More options",
        agentCreate: "Agent manage",
        details: "Task details",
        notes: "Notes",
        planDate: "Plan date",
        dueDate: "Due date",
        dueTime: "Time",
        remindAt: "Remind me",
        reminderChannel: "Reminder channel",
        reminderRecipient: "Recipient",
        reminderBackup: "Backup channel (optional)",
        reminderBackupRecipient: "Backup recipient",
        reminderRefresh: "Refresh channels",
        reminderTest: "Send test to primary",
        reminderAccepted: "Platform accepted the test",
        reminderLatest: "Latest delivery",
        schedulerLinked: "Linked scheduler task",
        schedulerPending: "Reminder schedule is pending; it will retry automatically.",
        priority: "Priority",
        priorities: ["None", "Low", "Medium", "High"],
        repeat: "Repeat",
        repeats: ["Never", "Daily", "Weekly", "Monthly", "Yearly"],
        repeatUntil: "End date",
        subtask: "Subtasks",
        addSubtask: "Add a subtask",
        subtaskHint: "Break this task into steps",
        parent: "Parent task",
        dependencies: "After these tasks",
        addDependency: "Add prerequisite",
        dependencyWaiting: "Waiting for prerequisite",
        topLevel: "Top level",
        more: "More properties",
        save: "Save changes",
        delete: "Delete task",
        deleteConfirm: "Delete this task and all its subtasks?",
        unfinished:
          "Some subtasks are still open. Complete only this parent task?",
        finishParent: "All subtasks are done. Complete the parent task?",
        statusNames: {
          todo: "To do",
          in_progress: "In progress",
          waiting: "Waiting",
          blocked: "Blocked",
          completed: "Completed",
          cancelled: "Cancelled",
        },
        progress: (done: number, total: number) => `${done} / ${total} done`,
        created: "Created",
        finished: "Completed",
        legacyChecklist: "Existing checklist",
        addStep: "Add a checklist item",
        recurrenceHint: "Repeating tasks cannot have subtasks.",
        uncertain: "These reminders may not have appeared on your device.",
        retry: "Send again",
        reminderInvalid:
          "The task changed or was completed, so that reminder was cancelled.",
        moveUp: "Move up",
        moveDown: "Move down",
        focus: "Focus on task",
        backToTree: "Back to task tree",
        breadcrumb: "Task path",
        focusHint: "Work through one level at a time",
        childEmpty: "No subtasks yet. Add the first step below.",
        edit: "Edit details",
        moveTo: "Move to",
        taskActions: "Task actions",
      }
    : {
        title: "事务",
        subtitle: "把需要完成的事安排清楚。",
        newTask: "新建事务",
        today: "今天",
        upcoming: "即将到期",
        all: "全部事务",
        incomplete: "未完成",
        completed: "已完成",
        cancelled: "已取消",
        search: "搜索事务",
        list: "清单 / 项目",
        allLists: "全部清单",
        tags: "标签",
        allTags: "全部标签",
        flagged: "已旗标",
        allFlags: "全部旗标",
        status: "状态",
        allStatuses: "全部状态",
        sort: "排序",
        dateSort: "日期",
        prioritySort: "优先级",
        manualSort: "手动顺序",
        overdue: "逾期",
        later: "后续",
        noDate: "无日期",
        empty: "这个视图还没有事务",
        createHint: "需要完成什么？",
        advanced: "更多选项",
        agentCreate: "Agent 管理",
        details: "事务详情",
        notes: "备注",
        planDate: "计划日期",
        dueDate: "截止日期",
        dueTime: "时间",
        remindAt: "提醒时间",
        reminderChannel: "提醒渠道",
        reminderRecipient: "接收人",
        reminderBackup: "备用渠道（可选）",
        reminderBackupRecipient: "备用接收人",
        reminderRefresh: "刷新渠道",
        reminderTest: "测试发送至首选渠道",
        reminderAccepted: "测试消息已被平台接受",
        reminderLatest: "最近投递",
        schedulerLinked: "已关联定时任务",
        schedulerPending: "提醒排程暂未同步成功，系统会自动重试。",
        priority: "优先级",
        priorities: ["无", "低", "中", "高"],
        repeat: "重复",
        repeats: ["不重复", "每天", "每周", "每月", "每年"],
        repeatUntil: "结束日期",
        subtask: "子事务",
        addSubtask: "添加子事务",
        subtaskHint: "需要时再拆解成步骤",
        parent: "父事务",
        dependencies: "前置事务",
        addDependency: "添加前置事务",
        dependencyWaiting: "等待前置事务",
        topLevel: "顶层事务",
        more: "更多属性",
        save: "保存修改",
        delete: "删除事务",
        deleteConfirm: "删除这条事务及其所有子事务？",
        unfinished: "仍有未完成的子事务。只完成父事务，保留子事务原状态？",
        finishParent: "所有子事务都已完成，是否完成父事务？",
        statusNames: {
          todo: "待处理",
          in_progress: "进行中",
          waiting: "等待中",
          blocked: "被阻塞",
          completed: "已完成",
          cancelled: "已取消",
        },
        progress: (done: number, total: number) => `${done} / ${total} 已完成`,
        created: "创建于",
        finished: "完成于",
        legacyChecklist: "原有检查清单",
        addStep: "添加清单项",
        recurrenceHint: "重复事务不能添加子事务。",
        uncertain: "以下提醒可能未在设备上显示。",
        retry: "重新发送",
        reminderInvalid: "事务已修改或完成，原提醒已取消。",
        moveUp: "上移",
        moveDown: "下移",
        focus: "聚焦此事务",
        backToTree: "返回事务树",
        breadcrumb: "事务路径",
        focusHint: "逐层处理，专注当前事务",
        childEmpty: "还没有子事务，在下方添加第一步。",
        edit: "编辑详情",
        moveTo: "移动到",
        taskActions: "事务操作",
      };
  const [rows, setRows] = useState<Todo[]>([]);
  const [templates, setTemplates] = useState<Todo[]>([]);
  const [uncertain, setUncertain] = useState<UncertainReminder[]>([]);
  const [view, setView] = useState<TodoView>("all");
  const [query, setQuery] = useState("");
  const [listFilter, setListFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [flagFilter, setFlagFilter] = useState(false);
  const [statusFilter, setStatusFilter] = useState<Todo["status"] | "">("");
  const [sort, setSort] = useState<Sort>("date");
  const [expanded, setExpanded] = useState<string[]>([]);
  const [inlineChildParent, setInlineChildParent] = useState<string | null>(null);
  const [inlineChildTitle, setInlineChildTitle] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<TodoInput | null>(null);
  const [draftTags, setDraftTags] = useState("");
  const [reminderDestinations, setReminderDestinations] = useState<Awaited<ReturnType<typeof apiClient.getTaskDestinations>>>([]);
  const [reminderTestStatus, setReminderTestStatus] = useState("");
  const [reminderTesting, setReminderTesting] = useState(false);
  const refreshReminderDestinations = useCallback(() => {
    void apiClient.getTaskDestinations().then(setReminderDestinations).catch((cause) =>
      setReminderTestStatus(cause instanceof Error ? cause.message : String(cause)));
  }, []);
  const [more, setMore] = useState(false);
  const [quickTitle, setQuickTitle] = useState("");
  const [quickOptions, setQuickOptions] = useState(false);
  const [quickDate, setQuickDate] = useState("");
  const [quickDue, setQuickDue] = useState("");
  const [quickReminder, setQuickReminder] = useState("");
  const [appleMenu, setAppleMenu] = useState(false);
  const [agentPreset, setAgentPreset] = useState<PresetRequest | undefined>();
  const [childTitle, setChildTitle] = useState("");
  const [dependencyChoice, setDependencyChoice] = useState("");
  const [dragId, setDragId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [compactBreadcrumb, setCompactBreadcrumb] = useState(false);
  const pageRef = useRef<HTMLDivElement>(null);
  const pathRef = useRef<string[]>([]);
  const treeRef = useRef<{ scrollTop: number; selectedId: string | null }>({ scrollTop: 0, selectedId: null });
  const [now, setNow] = useState(() => new Date());
  const today = dateKey(now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  const refresh = useCallback(async () => {
    try {
      const [all, focus, reminders] = await Promise.all([
        apiClient.getTodos(),
        apiClient.getTodoFocus(dateKey(new Date())),
        apiClient.getUncertainReminders(),
      ]);
      setTemplates(all);
      setRows(focus);
      setUncertain(reminders);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    apiClient.setBaseUrl(baseUrl);
    void refresh();
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [baseUrl, refresh]);
  const byId = useMemo(
    () => new Map(rows.map((todo) => [todo.id, todo])),
    [rows],
  );
  const selected = selectedId ? byId.get(selectedId) || null : null;
  const focused = focusedId ? byId.get(focusedId) || null : null;
  const focusPath = focusedId ? todoPath(focusedId, byId) : [];
  if (focused) pathRef.current = focusPath.map((item) => item.id);
  useEffect(() => {
    if (!focusedId || loading || byId.has(focusedId)) return;
    const ancestor = survivingFocus(focusedId, pathRef.current, byId);
    setFocusedId(ancestor);
    if (!ancestor) requestAnimationFrame(() => {
      if (pageRef.current) pageRef.current.scrollTop = treeRef.current.scrollTop;
    });
  }, [byId, focusedId, loading]);
  useEffect(() => {
    const resize = () => setCompactBreadcrumb(window.innerWidth < 700);
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const children = useCallback(
    (parentId: string | null) =>
      rows.filter((todo) => todo.parent_id === parentId && !todo.series_id),
    [rows],
  );
  const lists = useMemo(
    () =>
      [
        ...new Set(templates.map((todo) => todo.list_name).filter(Boolean)),
      ].sort(),
    [templates],
  );
  const tags = useMemo(
    () => [...new Set(templates.flatMap(tagsOf))].sort(),
    [templates],
  );
  const matchesView = (todo: Todo, target: TodoView) => matchesTodoView(todo, target, now);
  const subtreeMatchesView = (todo: Todo, target: TodoView): boolean =>
    matchesView(todo, target) ||
    children(todo.id).some((child) => subtreeMatchesView(child, target));
  const views: TodoView[] = [
    "all",
    "upcoming",
    "overdue",
    "incomplete",
    "completed",
  ];
  const counts = Object.fromEntries(
    views.map((key) => [
      key,
      rows.filter((todo) => !todo.parent_id && subtreeMatchesView(todo, key))
        .length,
    ]),
  ) as Record<TodoView, number>;
  const matchesFilters = (todo: Todo) => {
    if (listFilter && todo.list_name !== listFilter) return false;
    if (tagFilter && !tagsOf(todo).includes(tagFilter)) return false;
    if (flagFilter && !todo.flagged) return false;
    if (statusFilter && todo.status !== statusFilter) return false;
    if (
      query &&
      !`${todo.title} ${todo.notes} ${todo.list_name} ${tagsOf(todo).join(" ")}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase())
    )
      return false;
    return true;
  };
  const containsMatch = (todo: Todo): boolean =>
    matchesFilters(todo) || children(todo.id).some(containsMatch);
  const compare = (a: Todo, b: Todo) => {
    if (view === "all") {
      const rank = (todo: Todo) => todo.status === "completed" ? 3 : todo.status === "cancelled" ? 2 : isOverdue(todo, now) ? 0 : 1;
      const difference = rank(a) - rank(b);
      if (difference) return difference;
    }
    return sort === "manual"
      ? a.sort_order - b.sort_order || a.created_at.localeCompare(b.created_at)
      : sort === "priority"
        ? b.priority - a.priority ||
          (taskDate(a) || "9999").localeCompare(taskDate(b) || "9999")
        : (taskDate(a) || "9999").localeCompare(taskDate(b) || "9999") ||
          b.priority - a.priority ||
          a.sort_order - b.sort_order;
  };
  const roots = rows
    .filter(
      (todo) =>
        !todo.parent_id &&
        subtreeMatchesView(todo, view) &&
        containsMatch(todo),
    )
    .sort(compare);
  const hasOverdueDescendant = (todo: Todo): boolean =>
    children(todo.id).some((child) => isOverdue(child, now) || hasOverdueDescendant(child));
  const groups = new Map<string, Todo[]>();
  for (const todo of roots) {
    const day =
      taskDate(todo) ||
      children(todo.id)
        .filter((child) => subtreeMatchesView(child, view))
        .map(taskDate)
        .filter((value): value is string => !!value)
        .sort()[0];
    const group = todoGroup(todo, day || null, now,
      (view === "all" || view === "overdue") && hasOverdueDescendant(todo), view);
    groups.set(group, [...(groups.get(group) || []), todo]);
  }
  const run = async (operation: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await operation();
      await refresh();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(
        message.startsWith("unfinished_dependencies")
          ? copy.dependencyWaiting
          : message,
      );
    } finally {
      setBusy(false);
    }
  };
  const open = (todo: Todo) => {
    const original =
      templates.find((item) => item.id === taskKey(todo)) || todo;
    setSelectedId(todo.id);
    setDraft({
      title: original.title,
      notes: original.notes,
      due_on: original.due_on,
      due_time: original.due_time,
      timezone: original.timezone,
      priority: original.priority,
      repeat_frequency: original.repeat_frequency,
      repeat_days: JSON.parse(original.repeat_days || "[]"),
      repeat_until: original.repeat_until,
      planned_on: original.planned_on,
      list_name: original.list_name,
      tags: tagsOf(original),
      flagged: !!original.flagged,
      checklist: checklistOf(original),
      remind_at: original.remind_at,
      reminder_delivery: original.reminder_delivery || { primary: null, backup_enabled: false, backup: null },
    });
    setDraftTags(tagsOf(original).join(", "));
    setChildTitle("");
    setDependencyChoice("");
    setMore(false);
    setError("");
    setReminderTestStatus("");
    refreshReminderDestinations();
  };
  const close = () => {
    setSelectedId(null);
    setDraft(null);
    setError("");
  };
  const enterFocus = (todo: Todo) => {
    if (!focusedId) {
      treeRef.current = { scrollTop: pageRef.current?.scrollTop || 0, selectedId };
    }
    close();
    setChildTitle("");
    setFocusedId(todo.id);
    if (pageRef.current) pageRef.current.scrollTop = 0;
  };
  useEffect(() => {
    const todoId = (location.state as { todoId?: string } | null)?.todoId;
    const target = todoId ? byId.get(todoId) : null;
    if (!target) return;
    enterFocus(target);
    navigate("/todos", { replace: true, state: null });
  }, [rows, location.state, navigate]);
  const exitFocus = () => {
    setFocusedId(null);
    const previous = treeRef.current.selectedId;
    setSelectedId(previous && byId.has(previous) ? previous : null);
    setDraft(null);
    requestAnimationFrame(() => {
      if (pageRef.current) pageRef.current.scrollTop = treeRef.current.scrollTop;
    });
  };
  const createWithAgent = () => {
    const requirement = quickTitle.trim();
    if (!requirement || busy) return;
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const details = [
      requirement,
      quickDate && `${en ? "Planned date" : "计划日期"}: ${quickDate}`,
      quickDue && `${en ? "Due date" : "截止日期"}: ${quickDue}`,
      quickReminder && `${en ? "Reminder" : "提醒时间"}: ${fromLocalTime(quickReminder)} (${zone})`,
    ].filter(Boolean).join("\n");
    const prompt = en
      ? `Use the todos tool to create tasks from these requirements. Ask if essential details are missing; do not invent deadlines.\n\n${details}`
      : `请使用 todos 事务工具建立事务。若缺少必要信息，先询问我；不要自行编造截止时间。\n\n${details}`;
    setAgentPreset(enqueueEmbeddedPreset('todos', prompt));
    setQuickTitle("");
  };
  const createDirect = () => {
    const title = quickTitle.trim();
    if (!title || busy) return;
    void run(async () => {
      await apiClient.createTodo({ title, planned_on: quickDate || null, due_on: quickDue || null,
        remind_at: quickReminder ? fromLocalTime(quickReminder) : null });
      setQuickTitle(""); setQuickDate(""); setQuickDue(""); setQuickReminder("");
    });
  };
  const askAppleAgent = (text: string) => {
    setAgentPreset(enqueueEmbeddedPreset('todos', text));
    setAppleMenu(false);
  };
  const save = () => {
    if (!selected || !draft?.title.trim()) return;
    void run(async () => {
      const payload: TodoInput = {
        ...draft,
        title: draft.title.trim(),
        tags: draftTags
          .split(/[,，]/)
          .map((value) => value.trim())
          .filter(Boolean),
        repeat_days:
          draft.repeat_frequency === "weekly" ? draft.repeat_days : [],
      };
      if (!payload.remind_at) delete payload.reminder_delivery;
      await apiClient.updateTodo(taskKey(selected), payload);
    });
  };
  const changeReminderRoute = (change: (route: NotificationRoute) => NotificationRoute) => {
    setDraft((current) => current ? { ...current, reminder_delivery: change(current.reminder_delivery ||
      { primary: null, backup_enabled: false, backup: null }) } : current);
  };
  const testReminder = async () => {
    setReminderTesting(true);
    setReminderTestStatus("");
    try {
      const result = await apiClient.testNotificationRoute(draft?.reminder_delivery || null);
      setReminderTestStatus(result.status === "success"
        ? result.delivery_status === "accepted" ? copy.reminderAccepted : result.error || result.delivery_status || ""
        : result.message || "");
    } catch (cause) {
      setReminderTestStatus(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setReminderTesting(false);
    }
  };
  const changeStatus = (todo: Todo, status: Todo["status"]) =>
    void run(async () => {
      try {
        await apiClient.changeTodoStatus(todo.id, status);
      } catch (cause) {
        if (
          status === "completed" &&
          cause instanceof Error &&
          cause.message.includes("unfinished_subtasks")
        ) {
          if (window.confirm(copy.unfinished))
            await apiClient.changeTodoStatus(todo.id, status, true);
        } else throw cause;
      }
    });
  const toggle = (todo: Todo) =>
    changeStatus(todo, todo.status === "completed" ? "todo" : "completed");
  const move = (id: string, parentId: string | null, position?: number) =>
    void run(() => apiClient.moveTodo(id, parentId, position));
  const addFocusedChild = () => {
    if (!focused || !childTitle.trim()) return;
    void run(async () => {
      await apiClient.addSubtask(focused.id, { title: childTitle.trim() });
      setChildTitle("");
    });
  };
  const addInlineChild = (parentId: string) => {
    if (!inlineChildTitle.trim()) return;
    void run(async () => {
      await apiClient.addSubtask(parentId, { title: inlineChildTitle.trim() });
      setInlineChildTitle("");
      setInlineChildParent(null);
      setExpanded((value) => value.includes(parentId) ? value : [...value, parentId]);
    });
  };
  const deleteFocusedChild = (todo: Todo) => {
    if (!window.confirm(copy.deleteConfirm)) return;
    void run(() => apiClient.deleteTodo(todo.id));
  };
  const remove = () => {
    if (!selected || !window.confirm(copy.deleteConfirm)) return;
    void run(async () => {
      await apiClient.deleteTodo(taskKey(selected));
      close();
    });
  };
  const moveInList = (sourceId: string, target: Todo) => {
    const source = byId.get(sourceId);
    if (
      !source ||
      source.id === target.id ||
      source.series_id ||
      target.series_id
    )
      return;
    const siblings = children(target.parent_id)
      .filter((item) => item.id !== sourceId)
      .sort((a, b) => a.sort_order - b.sort_order);
    const position = siblings.findIndex((item) => item.id === target.id);
    if (position >= 0) move(sourceId, target.parent_id, position);
  };
  const row = (todo: Todo, depth = 0): React.ReactNode => {
    const sub = children(todo.id).sort(compare);
    const isExpanded =
      expanded.includes(todo.id) ||
      !!query ||
      (!matchesView(todo, view) &&
        sub.some((child) => subtreeMatchesView(child, view)));
    const visibleChildren = sub.filter((child) => subtreeMatchesView(child, view) && containsMatch(child));
    return (
      <React.Fragment key={todo.id}>
        <div
          draggable={!todo.series_id}
          onDragStart={(event) => {
            setDragId(todo.id);
            event.dataTransfer.effectAllowed = "move";
          }}
          onDragEnd={() => setDragId(null)}
          onDragOver={(event) => {
            if (dragId && dragId !== todo.id) event.preventDefault();
          }}
          onDrop={(event) => {
            event.preventDefault();
            if (dragId) moveInList(dragId, todo);
            setDragId(null);
          }}
          className={`group flex items-start gap-2 border-b border-default/70 py-2.5 pr-3 hover:bg-surface-2/60 ${selectedId === todo.id ? "bg-accent/5" : ""}`}
          style={{ paddingLeft: `${12 + Math.min(depth, 5) * 21}px` }}
        >
          <GripVertical
            size={15}
            className="mt-1 shrink-0 text-content-tertiary/50 hidden sm:block cursor-grab"
            aria-hidden="true"
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => toggle(todo)}
            aria-label={`${todo.status === "completed" ? copy.statusNames.completed : copy.statusNames.todo} ${todo.title}`}
            className={`mt-0.5 w-5 h-5 shrink-0 rounded-full border flex items-center justify-center ${todo.status === "completed" ? "bg-accent border-accent text-accent-contrast" : todo.status === "cancelled" ? "border-content-tertiary text-content-tertiary" : "border-content-tertiary hover:border-accent"}`}
          >
            {todo.status === "completed" && <Check size={12} />}
            {todo.status === "cancelled" && <X size={11} />}
          </button>
          <div className="flex-1 min-w-0">
            <button
              type="button"
              onClick={() => enterFocus(todo)}
              title={copy.focus}
              className="block w-full text-left"
            >
              <span
                className={`block text-sm font-medium truncate ${isDone(todo) ? "line-through text-content-tertiary" : "text-content-primary"}`}
              >
                {todo.title}
              </span>
              {(todo.subtask_count > 0 ||
                todo.status !== "todo" ||
                todo.due_on ||
                todo.planned_on ||
                todo.flagged ||
                todo.blocked_by.length > 0 ||
                todo.priority > 0 ||
                todo.repeat_frequency !== "none" ||
                todo.remind_at) && (
                <span className="flex flex-wrap gap-x-3 gap-y-0.5 items-center text-xs text-content-tertiary mt-0.5">
                  {todo.subtask_count > 0 && (
                    <span className="text-accent">
                      {copy.progress(
                        todo.progress_completed,
                        todo.progress_total,
                      )}
                    </span>
                  )}
                  {todo.status !== "todo" && (
                    <span className={statusColors[todo.status]}>
                      {copy.statusNames[todo.status]}
                    </span>
                  )}
                  {todo.blocked_by.length > 0 && (
                    <span className="text-amber-500">
                      {copy.dependencyWaiting}
                    </span>
                  )}
                  {todo.due_on && (
                    <span
                      title={copy.dueDate}
                      className={
                        isOverdue(todo, now)
                          ? "text-danger"
                          : ""
                      }
                    >
                      <Clock3 size={11} className="inline mr-1" />
                      {todo.due_on}
                      {todo.due_time && ` ${todo.due_time}`}
                    </span>
                  )}
                  {todo.planned_on && (
                    <span title={copy.planDate}>
                      <CalendarDays size={11} className="inline mr-1" />
                      {todo.planned_on}
                    </span>
                  )}
                  {!!todo.flagged && (
                    <Flag size={11} className="text-amber-500" />
                  )}
                  {todo.priority > 0 && (
                    <span className="text-amber-500">
                      {"!".repeat(todo.priority)}
                    </span>
                  )}
                  {todo.repeat_frequency !== "none" && <Repeat2 size={11} />}
                  {todo.remind_at && <span title={copy.remindAt}><BellRing size={11} className="inline mr-1" />{toLocalTime(todo.remind_at).replace("T", " ")}</span>}
                </span>
              )}
              {todo.subtask_count > 0 && (
                <span className="block h-1 max-w-48 rounded-full bg-surface-3 mt-2 overflow-hidden">
                  <span
                    className="block h-full bg-accent"
                    style={{ width: `${todo.progress_percent}%` }}
                  />
                </span>
              )}
            </button>
          </div>
          {!todo.series_id && todo.repeat_frequency === "none" && (
            <button type="button" disabled={busy} onClick={() => {
              setInlineChildParent(todo.id);
              setInlineChildTitle("");
            }} aria-label={`${copy.addSubtask} ${todo.title}`}
              className="p-1 text-content-tertiary hover:text-accent disabled:opacity-40"><Plus size={16} /></button>
          )}
          {sub.length > 0 && (
            <button
              type="button"
              onClick={() =>
                setExpanded((value) =>
                  isExpanded
                    ? value.filter((id) => id !== todo.id)
                    : [...value, todo.id],
                )
              }
              aria-label={`${copy.subtask} ${todo.title}`}
              aria-expanded={isExpanded}
              className="p-1 text-content-tertiary hover:text-accent"
            >
              {isExpanded ? (
                <ChevronDown size={16} />
              ) : (
                <ChevronRight size={16} />
              )}
            </button>
          )}
        </div>
        {isExpanded && visibleChildren.map((child) => row(child, depth + 1))}
        {inlineChildParent === todo.id && (
          <form onSubmit={(event) => { event.preventDefault(); addInlineChild(todo.id); }}
            className="flex items-center gap-2 border-b border-default/70 py-2 pr-3"
            style={{ paddingLeft: `${34 + Math.min(depth, 5) * 21}px` }}>
            <input autoFocus value={inlineChildTitle} onChange={(event) => setInlineChildTitle(event.target.value)}
              placeholder={copy.subtaskHint} aria-label={`${copy.addSubtask} ${todo.title}`}
              className="min-w-0 flex-1 rounded-btn border border-default bg-surface-2 px-3 py-1.5 text-sm outline-none focus:border-accent" />
            <button type="submit" disabled={busy || !inlineChildTitle.trim()} className="text-accent disabled:opacity-40"><Plus size={17} /></button>
            <button type="button" onClick={() => setInlineChildParent(null)} className="text-content-tertiary"><X size={16} /></button>
          </form>
        )}
      </React.Fragment>
    );
  };
  const input =
    "w-full rounded-btn border border-default bg-surface-2 px-3 py-2 text-sm focus:outline-none focus:border-accent";
  const statusOptions: Todo["status"][] = [
    "todo",
    "in_progress",
    "waiting",
    "blocked",
    "completed",
    "cancelled",
  ];
  const parentChoices = rows.filter(
    (todo) =>
      !todo.series_id &&
      todo.repeat_frequency === "none" &&
      todo.id !== selected?.id,
  );
  const isDescendant = (candidate: Todo) => {
    let parent = candidate.parent_id ? byId.get(candidate.parent_id) : null;
    const visited = new Set<string>();
    while (parent && !visited.has(parent.id)) {
      visited.add(parent.id);
      if (parent.id === selected?.id) return true;
      parent = parent.parent_id ? byId.get(parent.parent_id) : null;
    }
    return false;
  };
  return (
    <div ref={pageRef} className="h-full overflow-y-auto bg-surface-0 text-content-primary">
      <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
        {focused && (
          <nav aria-label={copy.breadcrumb} className="mb-5 flex items-center gap-1.5 text-xs text-content-tertiary min-w-0">
            {(() => {
              const items = [
                { id: "stella", title: "Stella" },
                { id: "tasks", title: copy.title },
                ...focusPath.map((item) => ({ id: item.id, title: item.title })),
              ];
              const { hidden } = breadcrumbParts(items, compactBreadcrumb);
              const visibleIds = new Set(breadcrumbParts(items, compactBreadcrumb).visible.map((item) => item.id));
              return items.map((item, index) => {
                if (hidden.length && index === items.findIndex((entry) => entry.id === hidden[0].id)) {
                  return <React.Fragment key="hidden">
                    <ChevronRight size={13} className="shrink-0" />
                    <details className="relative group">
                      <summary className="list-none cursor-pointer rounded-btn px-1.5 py-1 hover:bg-surface-2 hover:text-accent" aria-label={en ? "Hidden path levels" : "隐藏的路径层级"}>…</summary>
                      <div className="absolute left-0 top-full z-30 mt-1 min-w-44 max-w-72 rounded-card border border-default bg-surface p-1 shadow-lg">
                        {hidden.map((entry) => <button key={entry.id} type="button" onClick={() => entry.id === "tasks" || entry.id === "stella" ? exitFocus() : enterFocus(byId.get(entry.id)!)} className="block w-full truncate rounded-btn px-2 py-1.5 text-left text-content-secondary hover:bg-surface-2 hover:text-accent" title={entry.title}>{entry.title}</button>)}
                      </div>
                    </details>
                  </React.Fragment>;
                }
                if (!visibleIds.has(item.id)) return null;
                return <React.Fragment key={item.id}>
                  {index > 0 && <ChevronRight size={13} className="shrink-0" />}
                  {index === items.length - 1 ? (
                    <span aria-current="page" className="max-w-40 truncate font-medium text-content-primary" title={item.title}>{item.title}</span>
                  ) : (
                    <button type="button" onClick={() => item.id === "stella" || item.id === "tasks" ? exitFocus() : enterFocus(byId.get(item.id)!)} className="max-w-32 truncate rounded-btn px-1 py-1 hover:bg-surface-2 hover:text-accent" title={item.title}>{item.title}</button>
                  )}
                </React.Fragment>;
              });
            })()}
          </nav>
        )}
        <header className="flex items-start justify-between gap-4 mb-6">
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-semibold tracking-tight">
              {focused ? focused.title : copy.title}
            </h1>
            <p className="text-sm text-content-tertiary mt-1">
              {focused ? copy.focusHint : copy.subtitle}
            </p>
          </div>
          {focused ? <button type="button" onClick={exitFocus} className="shrink-0 inline-flex items-center gap-1.5 rounded-btn border border-default bg-surface px-3 py-2 text-sm text-content-secondary hover:text-accent"><CornerUpLeft size={15} />{copy.backToTree}</button> : <button
            type="button"
            onClick={() => document.getElementById("todo-quick-title")?.focus()}
            className="inline-flex items-center gap-1.5 rounded-btn bg-accent text-accent-contrast px-3.5 py-2 text-sm font-medium"
          >
            <Plus size={16} />
            {copy.newTask}
          </button>}
        </header>
        {error && <p role="alert" className="mb-4 rounded-card border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">{error}</p>}
        {loading && <p role="status" className="mb-4 text-sm text-content-tertiary">{en ? "Loading tasks…" : "正在加载事务…"}</p>}
        {!focusedId && <div>
        <nav
          aria-label={copy.title}
          className="flex gap-1 border-b border-default mb-5 overflow-x-auto"
        >
          {views.map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setView(key)}
              className={`shrink-0 inline-flex items-center gap-2 px-3 py-2.5 border-b-2 text-sm transition-colors ${view === key ? "border-accent text-accent font-medium" : "border-transparent text-content-secondary hover:text-content-primary"}`}
            >
              {copy[key]}{" "}
              <span className="text-xs text-content-tertiary">
                {counts[key]}
              </span>
            </button>
          ))}
        </nav>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            createWithAgent();
          }}
          className="rounded-card border border-default bg-surface mb-3"
        >
          <div className="flex flex-wrap items-center gap-2 px-3 py-2">
            <input
              id="todo-quick-title"
              value={quickTitle}
              onChange={(event) => setQuickTitle(event.target.value)}
              placeholder={copy.createHint}
              aria-label={copy.createHint}
              className="min-w-[150px] flex-1 bg-transparent py-1 text-sm outline-none"
            />
            <div className="ml-auto flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
              <button
                type="button"
                onClick={() => setQuickOptions(!quickOptions)}
                aria-expanded={quickOptions}
                className="p-1.5 text-content-secondary hover:text-accent"
                title={copy.advanced}
              >
                <MoreHorizontal size={18} />
              </button>
              <button
                type="button"
                disabled={!quickTitle.trim() || busy}
                onClick={createDirect}
                className="rounded-btn border border-default px-3 py-1.5 text-sm text-content disabled:opacity-40"
              >
                {en ? "Add directly" : "直接添加"}
              </button>
              <button
                type="submit"
                disabled={!quickTitle.trim() || busy}
                className="rounded-btn bg-accent px-3 py-1.5 text-sm text-accent-contrast disabled:opacity-40"
              >
                {copy.agentCreate}
              </button>
              <div className="relative">
                <button type="button" aria-expanded={appleMenu} onClick={() => setAppleMenu(value => !value)} className="inline-flex items-center gap-1 rounded-btn border border-default px-3 py-1.5 text-sm text-content hover:bg-surface-2">Apple 提醒事项<ChevronDown size={13} /></button>
                {appleMenu && <div role="menu" aria-label="Apple 提醒事项操作" onKeyDown={event => { if (event.key === "Escape") setAppleMenu(false) }} className="absolute right-0 top-full z-30 mt-1 min-w-56 rounded-btn border border-default bg-surface p-1 shadow-lg">
                  <button type="button" role="menuitem" onClick={() => askAppleAgent("请查看 Apple 提醒事项权限和可用列表，帮我选择要导入的提醒事项，先预览变更，并在获得我确认后导入 Stella 事务。")} className="w-full rounded-btn px-3 py-2 text-left text-sm hover:bg-surface-2">从 Apple 导入（Agent）</button>
                  <button type="button" role="menuitem" onClick={() => askAppleAgent("请查看 Apple 提醒事项权限和可写列表，帮我选择要同步至 Apple 的 Stella 事务，先预览变更，并在获得我确认后执行。")} className="w-full rounded-btn px-3 py-2 text-left text-sm hover:bg-surface-2">同步至 Apple（Agent）</button>
                  <button type="button" role="menuitem" onClick={() => { setAppleMenu(false); navigate("/settings?tab=integrations&section=apple-reminders") }} className="w-full rounded-btn px-3 py-2 text-left text-sm hover:bg-surface-2">管理 Apple 提醒事项</button>
                </div>}
              </div>
            </div>
          </div>
          {quickOptions && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 px-4 py-3 border-t border-default text-xs">
              <label>
                {copy.planDate}
                <input
                  type="date"
                  value={quickDate}
                  onChange={(event) => setQuickDate(event.target.value)}
                  className={`${input} mt-1`}
                />
              </label>
              <label>
                {copy.dueDate}
                <input
                  type="date"
                  value={quickDue}
                  onChange={(event) => setQuickDue(event.target.value)}
                  className={`${input} mt-1`}
                />
              </label>
              <label>
                {copy.remindAt}
                <input
                  type="datetime-local"
                  value={quickReminder}
                  onChange={(event) => setQuickReminder(event.target.value)}
                  className={`${input} mt-1`}
                />
              </label>
            </div>
          )}
        </form>
        <div className="mb-5"><EmbeddedAgent context="todos" presetRequest={agentPreset} onRunDone={() => void refresh()} /></div>
        {uncertain.length > 0 && (
          <section className="border border-amber-500/40 bg-amber-500/10 rounded-card p-3 mb-5 text-sm">
            <div className="flex items-center gap-2 font-medium mb-2">
              <BellRing size={15} />
              {copy.uncertain}
            </div>
            {uncertain.map((item) => (
              <div
                key={item.delivery_id}
                className="flex justify-between items-center gap-3 py-1"
              >
                <span>{item.title}</span>
                <button
                  type="button"
                  onClick={() =>
                    void run(async () => {
                      const queued = await apiClient.retryUncertainReminder(
                        item.delivery_id,
                      );
                      if (!queued) setError(copy.reminderInvalid);
                    })
                  }
                  className="text-accent shrink-0"
                >
                  {copy.retry}
                </button>
              </div>
            ))}
          </section>
        )}
        <div className="flex flex-wrap gap-2 mb-5">
          <div className="relative flex-1 min-w-[180px]">
            <Search
              size={15}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
            />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={copy.search}
              aria-label={copy.search}
              className={`${input} pl-9`}
            />
          </div>
          <select
            aria-label={copy.list}
            value={listFilter}
            onChange={(event) => setListFilter(event.target.value)}
            className={`${input} w-auto max-w-36`}
          >
            <option value="">{copy.allLists}</option>
            {lists.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <select
            aria-label={copy.tags}
            value={tagFilter}
            onChange={(event) => setTagFilter(event.target.value)}
            className={`${input} w-auto max-w-32`}
          >
            <option value="">{copy.allTags}</option>
            {tags.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setFlagFilter(!flagFilter)}
            aria-pressed={flagFilter}
            className={`rounded-btn border px-3 text-sm ${flagFilter ? "border-accent text-accent bg-accent/10" : "border-default text-content-secondary bg-surface"}`}
          >
            <Flag size={15} aria-label={copy.flagged} />
          </button>
          <select
            aria-label={copy.status}
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as Todo["status"] | "")
            }
            className={`${input} w-auto max-w-36`}
          >
            <option value="">{copy.allStatuses}</option>
            {statusOptions.map((value) => (
              <option key={value} value={value}>
                {copy.statusNames[value]}
              </option>
            ))}
          </select>
          <select
            aria-label={copy.sort}
            value={sort}
            onChange={(event) => setSort(event.target.value as Sort)}
            className={`${input} w-auto max-w-36`}
          >
            <option value="date">{copy.dateSort}</option>
            <option value="priority">{copy.prioritySort}</option>
            <option value="manual">{copy.manualSort}</option>
          </select>
        </div>
        {loading ? null : roots.length === 0 ? (
          <div className="rounded-card border border-default bg-surface py-16 text-center text-content-tertiary text-sm">
            {copy.empty}
          </div>
        ) : (
          <div className="space-y-5">
            {(["overdue", "today", "upcoming", "later", "noDate", "cancelled", "completed"] as const).map(
              (key) => {
                const items = groups.get(key);
                if (!items?.length) return null;
                return (
                  <section key={key}>
                    <h2
                      className={`text-xs font-semibold uppercase tracking-wide mb-2 ${key === "overdue" ? "text-danger" : "text-content-secondary"}`}
                    >
                      {copy[key]}{" "}
                      <span className="font-normal text-content-tertiary ml-1">
                        {items.length}
                      </span>
                    </h2>
                    <div className="rounded-card border border-default bg-surface overflow-hidden">
                      {items.map((todo) => row(todo))}
                    </div>
                  </section>
                );
              },
            )}
          </div>
        )}
        </div>}
        {focused && (
          <div className="space-y-6">
            <section className="rounded-card border border-default bg-surface p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
                    <span className={statusColors[focused.status]}>{copy.statusNames[focused.status]}</span>
                    {focused.priority > 0 && <span className="text-amber-500"><Flag size={12} className="inline mr-1" />{copy.priorities[focused.priority]}</span>}
                    {focused.due_on && <span><Clock3 size={12} className="inline mr-1" />{focused.due_on}</span>}
                    {focused.planned_on && <span><CalendarDays size={12} className="inline mr-1" />{focused.planned_on}</span>}
                    {focused.list_name && <span>{focused.list_name}</span>}
                    {tagsOf(focused).map((tag) => <span key={tag}>#{tag}</span>)}
                  </div>
                  {focused.notes && <p className="mt-3 whitespace-pre-wrap text-sm text-content-secondary">{focused.notes}</p>}
                  {focused.subtask_count > 0 && <div className="mt-4 max-w-lg">
                    <div className="flex justify-between text-xs text-content-tertiary mb-1"><span>{copy.subtask}</span><span>{copy.progress(focused.progress_completed, focused.progress_total)}</span></div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full bg-accent" style={{ width: `${focused.progress_percent}%` }} /></div>
                  </div>}
                </div>
                <div className="flex gap-2">
                  <button type="button" disabled={busy} onClick={() => toggle(focused)} className="rounded-btn border border-default px-3 py-1.5 text-xs hover:text-accent">{focused.status === "completed" ? copy.statusNames.todo : copy.statusNames.completed}</button>
                  <button type="button" onClick={() => open(focused)} className="inline-flex items-center gap-1 rounded-btn border border-default px-3 py-1.5 text-xs hover:text-accent"><Pencil size={13} />{copy.edit}</button>
                </div>
              </div>
            </section>
            {selected && draft && selected.id === focused.id && (
            <section aria-label={copy.details} className="rounded-card border border-default bg-surface px-4 py-5 sm:px-6 space-y-5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {copy.details}
                </span>
                <button
                  type="button"
                  onClick={close}
                  aria-label={en ? "Close editor" : "关闭编辑"}
                  className="p-1.5 rounded-btn hover:bg-surface-2"
                >
                  <X size={18} />
                </button>
              </div>
              <div>
                <input
                  aria-label={copy.title}
                  value={draft.title}
                  onChange={(event) =>
                    setDraft({ ...draft, title: event.target.value })
                  }
                  className="w-full text-xl font-semibold bg-transparent outline-none border-b border-transparent focus:border-accent pb-1"
                />
                <textarea
                  aria-label={copy.notes}
                  value={draft.notes || ""}
                  onChange={(event) =>
                    setDraft({ ...draft, notes: event.target.value })
                  }
                  placeholder={copy.notes}
                  rows={3}
                  className="mt-3 w-full resize-y rounded-btn border border-default bg-surface-2 p-3 text-sm"
                />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(["todo", "in_progress", "completed"] as const).map((status) => (
                  <button
                    key={status}
                    type="button"
                    disabled={busy}
                    onClick={() => changeStatus(selected, status)}
                    className={`rounded-btn border px-3 py-1.5 text-xs ${selected.status === status ? "border-accent bg-accent/10 text-accent font-medium" : "border-default text-content-secondary"}`}
                  >
                    {copy.statusNames[status]}
                  </button>
                ))}
                <select
                  aria-label={copy.status}
                  value={
                    ["waiting", "blocked", "cancelled"].includes(selected.status)
                      ? selected.status
                      : ""
                  }
                  onChange={(event) => {
                    if (event.target.value)
                      changeStatus(
                        selected,
                        event.target.value as Todo["status"],
                      );
                  }}
                  className="rounded-btn border border-default bg-surface px-2 py-1.5 text-xs text-content-secondary"
                >
                  <option value="">{copy.advanced}</option>
                  {(["waiting", "blocked", "cancelled"] as const).map(
                    (status) => (
                      <option key={status} value={status}>
                        {copy.statusNames[status]}
                      </option>
                    ),
                  )}
                </select>
              </div>
              <section className="grid grid-cols-2 gap-3 text-xs">
                <label>
                  {copy.planDate}
                  <input
                    type="date"
                    value={draft.planned_on || ""}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        planned_on: event.target.value || null,
                      })
                    }
                    className={`${input} mt-1`}
                  />
                </label>
                <label>
                  {copy.dueDate}
                  <input
                    type="date"
                    value={draft.due_on || ""}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        due_on: event.target.value || null,
                        due_time: event.target.value ? draft.due_time : null,
                        repeat_frequency: event.target.value
                          ? draft.repeat_frequency
                          : "none",
                      })
                    }
                    className={`${input} mt-1`}
                  />
                </label>
                <label>
                  {copy.dueTime}
                  <input
                    type="time"
                    value={draft.due_time || ""}
                    disabled={!draft.due_on}
                    onChange={(event) =>
                      setDraft({ ...draft, due_time: event.target.value || null })
                    }
                    className={`${input} mt-1 disabled:opacity-40`}
                  />
                </label>
                <label>
                  {copy.remindAt}
                  <input
                    type="datetime-local"
                    value={toLocalTime(draft.remind_at || null)}
                    disabled={draft.repeat_frequency !== "none"}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        remind_at: fromLocalTime(event.target.value),
                      })
                    }
                    className={`${input} mt-1 disabled:opacity-40`}
                  />
                </label>
              </section>
              {draft.remind_at && <section className="space-y-3 rounded-card border border-default p-3 text-xs text-content-secondary">
                <label className="block">{copy.reminderChannel}
                  <select aria-label={copy.reminderChannel} value={draft.reminder_delivery?.primary?.channel_type || ""}
                    onChange={(event) => changeReminderRoute(() => ({
                      primary: event.target.value ? { channel_type: event.target.value as 'web' | 'feishu' | 'weixin', receiver: "" } : null,
                      backup_enabled: false, backup: null,
                    }))} className={`${input} mt-1`}>
                    <option value="">{en ? "Desktop (default)" : "桌面提醒（默认）"}</option>
                    {reminderDestinations.filter((item) => item.configured || item.channel_type === draft.reminder_delivery?.primary?.channel_type)
                      .map((item) => <option key={item.channel_type} value={item.channel_type}>
                        {item.channel_type} · {item.status}
                      </option>)}
                  </select>
                </label>
                <button type="button" className="text-accent hover:underline" onClick={refreshReminderDestinations}>{copy.reminderRefresh}</button>
                {draft.reminder_delivery?.primary && <>
                  {draft.reminder_delivery.primary.channel_type === 'feishu' && <label className="block">{en ? 'Feishu recipient type' : '飞书接收人类型'}
                    <select aria-label={en ? 'Feishu recipient type' : '飞书接收人类型'} className={`${input} mt-1`}
                      value={draft.reminder_delivery.primary.receive_id_type || 'open_id'}
                      onChange={event => changeReminderRoute(route => ({...route, primary: {...route.primary!, receive_id_type: event.target.value,
                        is_group: event.target.value === 'chat_id'}}))}>
                      {['open_id', 'user_id', 'union_id', 'email', 'chat_id'].map(value => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>}
                  <label className="block">{copy.reminderRecipient}
                    <input aria-label={copy.reminderRecipient} list="todo-reminder-recipients" value={draft.reminder_delivery.primary.receiver}
                      onChange={event => changeReminderRoute(route => ({...route, primary: {...route.primary!, receiver: event.target.value}}))}
                      className={`${input} mt-1`} />
                    <datalist id="todo-reminder-recipients">{reminderDestinations.find(item => item.channel_type === draft.reminder_delivery?.primary?.channel_type)?.recipients
                      .map(item => <option key={item.receiver} value={item.receiver}>{item.name}</option>)}</datalist>
                  </label>
                  {draft.reminder_delivery.primary.channel_type === 'weixin' && <p>{en
                    ? 'Weixin delivery needs a recent conversation. Test now; the session may expire before the reminder.'
                    : '微信发送需要有效会话。可先测试，但提醒触发前会话仍可能失效。'}</p>}
                  <label className="flex items-center gap-2"><input type="checkbox" checked={draft.reminder_delivery.backup_enabled}
                    onChange={event => changeReminderRoute(route => ({...route, backup_enabled: event.target.checked,
                      backup: event.target.checked ? {channel_type: 'feishu', receiver: ''} : null}))} />{copy.reminderBackup}</label>
                  {draft.reminder_delivery.backup_enabled && <>
                    <select aria-label={copy.reminderBackup} value={draft.reminder_delivery.backup?.channel_type || 'feishu'}
                      onChange={event => changeReminderRoute(route => ({...route, backup: {channel_type: event.target.value as 'web' | 'feishu' | 'weixin', receiver: ''}}))}
                      className={input}>
                      {reminderDestinations.filter(item => item.configured || item.channel_type === draft.reminder_delivery?.backup?.channel_type)
                        .map(item => <option key={item.channel_type} value={item.channel_type}>{item.channel_type} · {item.status}</option>)}
                    </select>
                    {draft.reminder_delivery.backup?.channel_type === 'feishu' && <select aria-label={en ? 'Backup Feishu recipient type' : '备用飞书接收人类型'}
                      className={input} value={draft.reminder_delivery.backup.receive_id_type || 'open_id'}
                      onChange={event => changeReminderRoute(route => ({...route, backup: {...route.backup!, receive_id_type: event.target.value,
                        is_group: event.target.value === 'chat_id'}}))}>
                      {['open_id', 'user_id', 'union_id', 'email', 'chat_id'].map(value => <option key={value} value={value}>{value}</option>)}
                    </select>}
                    <label className="block">{copy.reminderBackupRecipient}
                      <input aria-label={copy.reminderBackupRecipient} value={draft.reminder_delivery.backup?.receiver || ''}
                        onChange={event => changeReminderRoute(route => ({...route, backup: {...route.backup!, receiver: event.target.value}}))}
                        className={`${input} mt-1`} />
                    </label>
                  </>}
                  <button type="button" disabled={reminderTesting || !draft.reminder_delivery.primary.receiver.trim()}
                    onClick={() => void testReminder()} className="text-accent hover:underline disabled:opacity-40">{copy.reminderTest}</button>
                </>}
                {reminderTestStatus && <p role="status">{reminderTestStatus}</p>}
                {selected.reminder_delivery_status && <p role="status">{copy.reminderLatest}: {selected.reminder_delivery_status.status}
                  {selected.reminder_delivery_status.error ? ` · ${selected.reminder_delivery_status.error}` : ''}</p>}
              </section>}
              {selected.reminder_sync_pending ? <p role="status" className="text-xs text-amber-500">{copy.schedulerPending}</p>
                : selected.scheduler_task_id && <button type="button" onClick={() => navigate("/tasks")}
                  className="text-xs text-accent text-left">{copy.schedulerLinked} · {selected.scheduler_task_id}</button>}
              <button
                type="button"
                onClick={() => setMore(!more)}
                aria-expanded={more}
                className="flex items-center gap-1 text-sm text-content-secondary hover:text-accent"
              >
                {more ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                {copy.more}
              </button>
              {more && (
                <section className="space-y-3 text-xs">
                  <label className="block">
                    {copy.priority}
                    <select
                      value={draft.priority || 0}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          priority: Number(event.target.value),
                        })
                      }
                      className={`${input} mt-1`}
                    >
                      {copy.priorities.map((name, value) => (
                        <option key={name} value={value}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    {copy.list}
                    <input
                      list="todo-lists"
                      value={draft.list_name || ""}
                      onChange={(event) =>
                        setDraft({ ...draft, list_name: event.target.value })
                      }
                      className={`${input} mt-1`}
                    />
                    <datalist id="todo-lists">
                      {lists.map((name) => (
                        <option key={name} value={name} />
                      ))}
                    </datalist>
                  </label>
                  <label className="block">
                    {copy.tags}
                    <input
                      value={draftTags}
                      onChange={(event) => setDraftTags(event.target.value)}
                      className={`${input} mt-1`}
                    />
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={!!draft.flagged}
                      onChange={(event) =>
                        setDraft({ ...draft, flagged: event.target.checked })
                      }
                    />
                    {copy.flagged}
                  </label>
                  <label className="block">
                    {copy.parent}
                    <select
                      value={selected.parent_id || ""}
                      onChange={(event) =>
                        move(taskKey(selected), event.target.value || null)
                      }
                      disabled={selected.repeat_frequency !== "none"}
                      className={`${input} mt-1`}
                    >
                      <option value="">{copy.topLevel}</option>
                      {parentChoices
                        .filter((candidate) => !isDescendant(candidate))
                        .map((candidate) => (
                          <option key={candidate.id} value={candidate.id}>
                            {candidate.title}
                          </option>
                        ))}
                    </select>
                  </label>
                  {selected.repeat_frequency === "none" && (
                    <div className="space-y-2">
                      <div className="font-medium">{copy.dependencies}</div>
                      {selected.dependency_ids.map((id) => (
                        <div key={id} className="flex items-center gap-2">
                          <span
                            className={`flex-1 truncate ${selected.blocked_by.includes(id) ? "text-amber-500" : "text-content-secondary"}`}
                          >
                            {byId.get(id)?.title || id}
                          </span>
                          <button
                            type="button"
                            aria-label={copy.delete}
                            onClick={() =>
                              void run(() =>
                                apiClient.removeTodoDependency(selected.id, id),
                              )
                            }
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ))}
                      <div className="flex gap-2">
                        <select
                          aria-label={copy.addDependency}
                          value={dependencyChoice}
                          onChange={(event) =>
                            setDependencyChoice(event.target.value)
                          }
                          className={`${input} flex-1`}
                        >
                          <option value="">{copy.addDependency}</option>
                          {parentChoices
                            .filter(
                              (item) =>
                                !selected.dependency_ids.includes(item.id),
                            )
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.title}
                              </option>
                            ))}
                        </select>
                        <button
                          type="button"
                          disabled={!dependencyChoice || busy}
                          onClick={() =>
                            void run(async () => {
                              await apiClient.addTodoDependency(
                                selected.id,
                                dependencyChoice,
                              );
                              setDependencyChoice("");
                            })
                          }
                          className="text-accent disabled:opacity-40"
                          aria-label={copy.addDependency}
                        >
                          <Plus size={18} />
                        </button>
                      </div>
                    </div>
                  )}
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        const siblings = children(selected.parent_id).sort(
                          (a, b) => a.sort_order - b.sort_order,
                        );
                        const index = siblings.findIndex(
                          (item) => item.id === selected.id,
                        );
                        if (index > 0)
                          move(selected.id, selected.parent_id, index - 1);
                      }}
                      className="rounded-btn border border-default px-2 py-1.5"
                    >
                      ↑ {copy.moveUp}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        const siblings = children(selected.parent_id).sort(
                          (a, b) => a.sort_order - b.sort_order,
                        );
                        const index = siblings.findIndex(
                          (item) => item.id === selected.id,
                        );
                        if (index < siblings.length - 1)
                          move(selected.id, selected.parent_id, index + 1);
                      }}
                      className="rounded-btn border border-default px-2 py-1.5"
                    >
                      ↓ {copy.moveDown}
                    </button>
                  </div>
                  <label className="block">
                    {copy.repeat}
                    <select
                      value={draft.repeat_frequency || "none"}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          repeat_frequency: event.target
                            .value as Todo["repeat_frequency"],
                          remind_at:
                            event.target.value === "none"
                              ? draft.remind_at
                              : null,
                        })
                      }
                      disabled={
                        !draft.due_on ||
                        selected.subtask_count > 0 ||
                        !!selected.parent_id
                      }
                      className={`${input} mt-1`}
                    >
                      {(
                        ["none", "daily", "weekly", "monthly", "yearly"] as const
                      ).map((value, index) => (
                        <option key={value} value={value}>
                          {copy.repeats[index]}
                        </option>
                      ))}
                    </select>
                  </label>
                  {draft.repeat_frequency !== "none" && (
                    <label className="block">
                      {copy.repeatUntil}
                      <input
                        type="date"
                        value={draft.repeat_until || ""}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            repeat_until: event.target.value || null,
                          })
                        }
                        className={`${input} mt-1`}
                      />
                    </label>
                  )}
                  {((draft.checklist?.length || 0) > 0 ||
                    selected.checklist !== "[]") && (
                    <div className="space-y-1">
                      <div className="font-medium">{copy.legacyChecklist}</div>
                      {(draft.checklist || []).map((step, index) => (
                        <div key={step.id} className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={
                              selected.repeat_frequency !== "none"
                                ? checklistOf(selected).find(
                                    (item) => item.id === step.id,
                                  )?.completed || false
                                : step.completed
                            }
                            onChange={() =>
                              selected.repeat_frequency !== "none"
                                ? void run(() =>
                                    apiClient.completeTodoChecklist(
                                      selected.id,
                                      step.id,
                                      !checklistOf(selected).find(
                                        (item) => item.id === step.id,
                                      )?.completed,
                                    ),
                                  )
                                : setDraft({
                                    ...draft,
                                    checklist: draft.checklist?.map((item) =>
                                      item.id === step.id
                                        ? { ...item, completed: !item.completed }
                                        : item,
                                    ),
                                  })
                            }
                          />
                          <input
                            aria-label={`${copy.legacyChecklist} ${index + 1}`}
                            value={step.title}
                            onChange={(event) =>
                              setDraft({
                                ...draft,
                                checklist: draft.checklist?.map((item) =>
                                  item.id === step.id
                                    ? { ...item, title: event.target.value }
                                    : item,
                                ),
                              })
                            }
                            className={`${input} flex-1`}
                          />
                          <button
                            type="button"
                            aria-label={copy.delete}
                            onClick={() =>
                              setDraft({
                                ...draft,
                                checklist: draft.checklist?.filter(
                                  (item) => item.id !== step.id,
                                ),
                              })
                            }
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <button
                    type="button"
                    className="text-accent"
                    onClick={() =>
                      setDraft({
                        ...draft,
                        checklist: [
                          ...(draft.checklist || []),
                          {
                            id: crypto.randomUUID(),
                            title: "",
                            completed: false,
                          },
                        ],
                      })
                    }
                  >
                    + {copy.addStep}
                  </button>
                </section>
              )}
              <div className="text-xs text-content-tertiary space-y-1">
                <div>
                  {copy.created}: {new Date(selected.created_at).toLocaleString()}
                </div>
                {selected.completed_at && (
                  <div>
                    {copy.finished}:{" "}
                    {new Date(selected.completed_at).toLocaleString()}
                  </div>
                )}
              </div>
              {error && (
                <p role="alert" className="text-sm text-danger">
                  {error}
                </p>
              )}
              <div className="border-t border-default pt-4 flex justify-between gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={remove}
                  className="text-danger text-sm inline-flex items-center gap-1"
                >
                  <Trash2 size={15} />
                  {copy.delete}
                </button>
                <button
                  type="button"
                  disabled={busy || !draft.title?.trim()}
                  onClick={save}
                  className="rounded-btn bg-accent px-4 py-2 text-accent-contrast text-sm disabled:opacity-40"
                >
                  {copy.save}
                </button>
              </div>
            </section>
            )}

            <section aria-label={copy.subtask}>
              <div className="flex items-center justify-between mb-3"><h2 className="text-sm font-semibold">{copy.subtask} <span className="font-normal text-content-tertiary">{focused.subtask_count}</span></h2><span className="text-xs text-content-tertiary">{copy.focusHint}</span></div>
              <div className="rounded-card border border-default bg-surface divide-y divide-default/70">
                {children(focused.id).sort((a, b) => a.sort_order - b.sort_order).map((child, index, siblings) => (
                  <div key={child.id} className="flex items-center gap-2 px-3 py-3 sm:px-4 hover:bg-surface-2/50">
                    <button type="button" disabled={busy} onClick={() => toggle(child)} aria-label={`${copy.statusNames[child.status]} ${child.title}`} className={`w-5 h-5 shrink-0 rounded-full border flex items-center justify-center ${child.status === "completed" ? "border-accent bg-accent text-accent-contrast" : "border-content-tertiary hover:border-accent"}`}>{child.status === "completed" && <Check size={12} />}</button>
                    <div className="min-w-0 flex-1">
                      <button type="button" onClick={() => enterFocus(child)} title={copy.focus} className={`block w-full truncate text-left text-sm font-medium hover:text-accent ${isDone(child) ? "line-through text-content-tertiary" : ""}`}>{child.title}</button>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-content-tertiary">
                        <span className={statusColors[child.status]}>{copy.statusNames[child.status]}</span>
                        {child.priority > 0 && <span className="text-amber-500">{copy.priority}: {copy.priorities[child.priority]}</span>}
                        {child.subtask_count > 0 && <span className="text-accent">{copy.progress(child.progress_completed, child.progress_total)}</span>}
                      </div>
                    </div>
                    <button type="button" onClick={() => { enterFocus(child); open(child); }} title={copy.edit} aria-label={`${copy.edit} ${child.title}`} className="shrink-0 rounded-btn p-1.5 text-content-tertiary hover:text-accent"><Pencil size={15} /></button>
                    <details className="relative shrink-0"><summary aria-label={`${copy.taskActions} ${child.title}`} className="list-none cursor-pointer rounded-btn p-1.5 text-content-tertiary hover:text-accent"><MoreHorizontal size={17} /></summary>
                      <div className="absolute right-0 top-full z-20 mt-1 w-52 rounded-card border border-default bg-surface p-2 shadow-lg space-y-1 text-xs">
                        <button type="button" disabled={busy || index === 0} onClick={() => move(child.id, focused.id, index - 1)} className="block w-full rounded-btn px-2 py-1 text-left hover:bg-surface-2 disabled:opacity-40">{copy.moveUp}</button>
                        <button type="button" disabled={busy || index === siblings.length - 1} onClick={() => move(child.id, focused.id, index + 1)} className="block w-full rounded-btn px-2 py-1 text-left hover:bg-surface-2 disabled:opacity-40">{copy.moveDown}</button>
                        <label className="block px-2">{copy.moveTo}<select aria-label={`${copy.moveTo} ${child.title}`} value={child.parent_id || ""} disabled={busy} onChange={(event) => move(child.id, event.target.value || null)} className={`${input} mt-1`}><option value="">{copy.topLevel}</option>{rows.filter((candidate) => !candidate.series_id && candidate.repeat_frequency === "none" && candidate.id !== child.id && !todoPath(candidate.id, byId).some((node) => node.id === child.id)).map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.title}</option>)}</select></label>
                        <button type="button" disabled={busy} onClick={() => deleteFocusedChild(child)} className="block w-full rounded-btn px-2 py-1 text-left text-danger hover:bg-surface-2">{copy.delete}</button>
                      </div>
                    </details>
                  </div>
                ))}
                {focused.subtask_count === 0 && <p className="px-4 py-8 text-center text-sm text-content-tertiary">{copy.childEmpty}</p>}
                {focused.repeat_frequency === "none" ? <form onSubmit={(event) => { event.preventDefault(); addFocusedChild(); }} className="flex gap-2 p-3 sm:p-4"><input value={childTitle} onChange={(event) => setChildTitle(event.target.value)} placeholder={copy.subtaskHint} aria-label={copy.addSubtask} className={`${input} flex-1 min-w-0`} /><button type="submit" disabled={busy || !childTitle.trim()} className="inline-flex items-center gap-1 rounded-btn bg-accent px-3 text-sm text-accent-contrast disabled:opacity-40"><Plus size={15} />{copy.addSubtask}</button></form> : <p className="p-4 text-xs text-content-tertiary">{copy.recurrenceHint}</p>}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
};

export default TodosPage;
