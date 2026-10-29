"""MySQL 表结构（幂等 DDL）。"""

SCHEMA = {
    "orders": """
        CREATE TABLE IF NOT EXISTS orders (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            order_no VARCHAR(32) NOT NULL COMMENT '订单号',
            user_id VARCHAR(32) NOT NULL COMMENT '用户ID',
            status VARCHAR(16) NOT NULL COMMENT 'PAID/SHIPPED/DELIVERED/REFUNDING/REFUNDED/CANCELLED/AFTER_SALE',
            amount DECIMAL(10, 2) NOT NULL DEFAULT 0,
            refundable_amount DECIMAL(10, 2) NOT NULL DEFAULT 0,
            logistics_no VARCHAR(32) NOT NULL DEFAULT '',
            product VARCHAR(128) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_order_no (order_no),
            KEY idx_user (user_id)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '合成订单数据（只读）'
    """,
    "tickets": """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id VARCHAR(32) NOT NULL,
            session_id VARCHAR(64) NOT NULL,
            user_id VARCHAR(32) NOT NULL,
            trace_id VARCHAR(32) NOT NULL,
            intent VARCHAR(32) NOT NULL DEFAULT 'unknown',
            confidence DECIMAL(4, 3) NOT NULL DEFAULT 0,
            risk_flag TINYINT(1) NOT NULL DEFAULT 0,
            raw_input TEXT,
            summary TEXT,
            draft_reply TEXT,
            status VARCHAR(16) NOT NULL DEFAULT 'ANSWERED',
            handoff_reason VARCHAR(64) DEFAULT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (ticket_id),
            KEY idx_session (session_id, created_at),
            KEY idx_trace (trace_id)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '工单处置结果'
    """,
    "handoff_tickets": """
        CREATE TABLE IF NOT EXISTS handoff_tickets (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            ticket_id VARCHAR(32) NOT NULL,
            trigger_type VARCHAR(64) NOT NULL,
            trigger_detail JSON,
            conversation_snapshot JSON,
            slots JSON,
            draft_reply TEXT,
            status VARCHAR(16) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN/CONFIRMED/RETURNED/EDITED',
            handler_action VARCHAR(16) DEFAULT NULL,
            handler_note VARCHAR(512) DEFAULT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            handled_at DATETIME DEFAULT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uk_ticket (ticket_id),
            KEY idx_status (status)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '转人工工单'
    """,
    "audit_logs": """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            trace_id VARCHAR(32) NOT NULL,
            node VARCHAR(32) NOT NULL,
            event VARCHAR(32) NOT NULL,
            intent VARCHAR(32) DEFAULT NULL,
            confidence DECIMAL(4, 3) DEFAULT NULL,
            tool_calls JSON,
            retrieval_sources JSON,
            handoff_trigger JSON,
            latency_ms INT NOT NULL DEFAULT 0,
            token_usage JSON,
            prompt_version VARCHAR(32) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_trace (trace_id),
            KEY idx_created (created_at)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '审计日志（可回放）'
    """,
    "regression_cases": """
        CREATE TABLE IF NOT EXISTS regression_cases (
            case_id VARCHAR(32) NOT NULL,
            category VARCHAR(16) NOT NULL,
            input_text TEXT NOT NULL,
            expected_status VARCHAR(16) NOT NULL DEFAULT '',
            expected_intent VARCHAR(32) NOT NULL DEFAULT '',
            assertions JSON,
            turns JSON,
            source_version VARCHAR(32) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (case_id)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '回归用例（只增不减）'
    """,
    "idempotency_keys": """
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            idem_key VARCHAR(64) NOT NULL,
            scope VARCHAR(32) NOT NULL,
            result_ref VARCHAR(64) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (idem_key),
            KEY idx_scope (scope)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '写操作幂等键'
    """,
}

CREATE_DATABASE = "CREATE DATABASE IF NOT EXISTS `{db}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
