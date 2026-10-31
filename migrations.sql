-- PY BANK: safe, idempotent migration for the Flask version.
-- The app runs this automatically at start-up (see database.py), but you can
-- also paste it into the Neon SQL Editor. It never deletes or rewrites data.

-- 1) Remember who the other party of a transfer was (nullable, so every
--    existing row stays valid).
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS counterparty_account TEXT;

-- 2) Allow the two new transaction types used by account-to-account transfers.
DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'transactions'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%transaction_type%'
      AND conname <> 'transactions_type_check_v2'
  LOOP
    EXECUTE format('ALTER TABLE transactions DROP CONSTRAINT %I', c.conname);
  END LOOP;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'transactions'::regclass
      AND conname = 'transactions_type_check_v2'
  ) THEN
    ALTER TABLE transactions ADD CONSTRAINT transactions_type_check_v2
      CHECK (transaction_type IN
        ('Opening', 'Deposit', 'Withdraw', 'Transfer In', 'Transfer Out'));
  END IF;
END $$;

-- 3) Helpful index for the dashboard chart / history queries (already exists
--    in the original schema, kept here for fresh databases).
CREATE INDEX IF NOT EXISTS idx_transactions_account_date
  ON transactions(account_no, created_at DESC);
