-- Add partial and needs_review to taskstatus enum (PostgreSQL 10+ supports IF NOT EXISTS)
ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'partial';
ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'needs_review';
