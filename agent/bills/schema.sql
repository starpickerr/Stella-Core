-- =============================================================================
-- Stella 账单模块 SQLite 表结构
--
-- 采用「基表 + 子表」拆分，另有周期账单快照：
--   financial_events          所有财务事件的公共字段（金额、类别、名称等）
--   planned_payments          计划付款（待缴账单 / 周期扣款），一对一扩展
--   ledger_entries            已发生流水（收入 / 支出），一对一扩展
--   period_statements         月度 / 年度账单汇总（由流水聚合生成）
--   period_statement_items    周期账单按类别 / 细项的明细
--
-- 金额统一用最小货币单位整数存储（amount_minor），例如人民币「分」。
-- 时间字段均为 ISO-8601 文本（UTC 或带时区），由应用层负责解析。
-- JSON 文本字段（reminder_days、scheduler_task_ids）由应用层读写。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 财务事件基表：计划付款与账本流水共享的公共信息
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_events (
    id            TEXT    PRIMARY KEY,                          -- 事件 ID
    event_type    TEXT    NOT NULL
                          CHECK (event_type IN (
                              'planned_payment',                -- 计划付款
                              'ledger_entry'                    -- 账本流水
                          )),
    amount_minor  INTEGER NOT NULL CHECK (amount_minor >= 0),   -- 金额（最小货币单位，非负）
    currency      TEXT    NOT NULL DEFAULT 'CNY',               -- ISO 4217 货币代码
    category      TEXT    NOT NULL DEFAULT '',                  -- 类别（如消费、转账、工资、退款）
    name          TEXT    NOT NULL,                             -- 名称 / 细项（如午餐、地铁、房租）；列表展示用此字段
    note          TEXT    NOT NULL DEFAULT '',                  -- 备注
    created_at    TEXT    NOT NULL,                             -- 创建时间
    updated_at    TEXT    NOT NULL                              -- 最后更新时间
);

-- -----------------------------------------------------------------------------
-- 计划付款：到期提醒、周期重复、完成后可生成对应流水
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS planned_payments (
    event_id            TEXT PRIMARY KEY,                       -- 对应 financial_events.id
    due_at              TEXT NOT NULL,                          -- 到期时间
    status              TEXT NOT NULL DEFAULT 'pending'
                             CHECK (status IN (
                                 'pending',                     -- 待支付
                                 'completed',                   -- 已完成
                                 'cancelled'                    -- 已取消
                             )),
    recurrence_type     TEXT NOT NULL DEFAULT 'none'
                             CHECK (recurrence_type IN (
                                 'none',                        -- 一次性
                                 'daily',
                                 'weekly',
                                 'monthly',
                                 'yearly',
                                 'custom'                       -- 由 recurrence_rule 描述
                             )),
    recurrence_rule     TEXT,                                   -- 自定义周期规则（如 RRULE / JSON）
    reminder_days       TEXT NOT NULL DEFAULT '[0]',            -- 提前提醒天数 JSON 数组；[0] 表示到期当天
    scheduler_task_ids  TEXT NOT NULL DEFAULT '[]',             -- 关联调度任务 ID 的 JSON 数组
    completed_at        TEXT,                                   -- 完成时间；未完成时为空
    FOREIGN KEY (event_id) REFERENCES financial_events(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 账本流水：实际发生的收入 / 支出记录
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ledger_entries (
    event_id            TEXT PRIMARY KEY,                       -- 对应 financial_events.id
    entry_type          TEXT NOT NULL
                             CHECK (entry_type IN (
                                 'income',                      -- 收入
                                 'expense'                      -- 支出
                             )),
    txn_type            TEXT NOT NULL DEFAULT '',               -- 交易类型：消费 / 转账 / 工资 / 退款 / 充值 等
    counterparty        TEXT NOT NULL DEFAULT '',               -- 交易对方；支付完成后回填
    occurred_at         TEXT NOT NULL,                          -- 实际发生时间
    status              TEXT NOT NULL DEFAULT 'posted'
                             CHECK (status IN (
                                 'pending',                     -- 待入账
                                 'posted',                      -- 已入账
                                 'reversed'                     -- 已冲正
                             )),
    account_id          TEXT,                                   -- 关联账户；可为空
    planned_payment_id  TEXT,                                   -- 由哪笔计划付款生成；可为空
    FOREIGN KEY (event_id) REFERENCES financial_events(id) ON DELETE CASCADE,
    FOREIGN KEY (planned_payment_id) REFERENCES planned_payments(event_id) ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 月度 / 年度账单：某周期内已入账流水的汇总快照
-- 月度：year + month；年度：year，month 为空
-- 可由 ledger_entries 按 occurred_at 重新生成
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS period_statements (
    id              TEXT    PRIMARY KEY,                        -- 账单 ID
    period_type     TEXT    NOT NULL
                            CHECK (period_type IN (
                                'monthly',                      -- 月度账单
                                'yearly'                        -- 年度账单
                            )),
    year            INTEGER NOT NULL CHECK (year >= 1),         -- 年份，如 2026
    month           INTEGER,                                    -- 月度填 1–12；年度为空
    start_at        TEXT    NOT NULL,                           -- 周期开始（含）
    end_at          TEXT    NOT NULL,                           -- 周期结束（不含）
    currency        TEXT    NOT NULL DEFAULT 'CNY',             -- ISO 4217 货币代码
    income_minor    INTEGER NOT NULL DEFAULT 0
                            CHECK (income_minor >= 0),          -- 周期内收入合计
    expense_minor   INTEGER NOT NULL DEFAULT 0
                            CHECK (expense_minor >= 0),         -- 周期内支出合计
    net_minor       INTEGER NOT NULL,                           -- 结余 = 收入 - 支出，可为负
    status          TEXT    NOT NULL DEFAULT 'open'
                            CHECK (status IN (
                                'open',                         -- 进行中（当月 / 当年），可随流水刷新
                                'closed'                        -- 已结账（往月 / 往年）
                            )),
    note            TEXT    NOT NULL DEFAULT '',                -- 备注
    generated_at    TEXT    NOT NULL,                           -- 最近一次由流水聚合的时间
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    CHECK (
        (period_type = 'monthly' AND month BETWEEN 1 AND 12)
        OR (period_type = 'yearly' AND month IS NULL)
    )
);

-- 同一货币下：每月一份、每年一份（年度 month 为空，需用部分唯一索引）
CREATE UNIQUE INDEX IF NOT EXISTS idx_period_statements_monthly
    ON period_statements(year, month, currency)
    WHERE period_type = 'monthly';

CREATE UNIQUE INDEX IF NOT EXISTS idx_period_statements_yearly
    ON period_statements(year, currency)
    WHERE period_type = 'yearly';

-- -----------------------------------------------------------------------------
-- 周期账单明细：按类别 + 名称汇总，如「消费 / 午餐」在该月 / 该年花了多少
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS period_statement_items (
    id              TEXT    PRIMARY KEY,
    statement_id    TEXT    NOT NULL,                           -- 对应 period_statements.id
    category        TEXT    NOT NULL DEFAULT '',                -- 类别（如消费）
    name            TEXT    NOT NULL DEFAULT '',                -- 细项（如午餐）
    entry_type      TEXT    NOT NULL
                            CHECK (entry_type IN (
                                'income',
                                'expense'
                            )),
    amount_minor    INTEGER NOT NULL CHECK (amount_minor >= 0), -- 该细项金额合计
    entry_count     INTEGER NOT NULL DEFAULT 0
                            CHECK (entry_count >= 0),           -- 该细项笔数
    FOREIGN KEY (statement_id) REFERENCES period_statements(id) ON DELETE CASCADE,
    UNIQUE (statement_id, category, name, entry_type)
);

CREATE INDEX IF NOT EXISTS idx_planned_payments_due
    ON planned_payments(status, due_at);

CREATE INDEX IF NOT EXISTS idx_ledger_entries_occurred
    ON ledger_entries(status, occurred_at);

-- Plugin API domain receipts (same DB transaction as business writes)
CREATE TABLE IF NOT EXISTS plugin_operation_receipts (
    operation_id    TEXT PRIMARY KEY,
    method          TEXT NOT NULL,
    request_digest  TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'unknown')),
    result_id       TEXT,
    error_code      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
