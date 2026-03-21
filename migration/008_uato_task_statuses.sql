-- UATO-specific task lifecycle values (PostgreSQL taskstatus enum).
ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'pending_approval';
ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'uato_blocked';
