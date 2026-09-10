-- =============================================================================
-- An option belongs to an operator, not to the building.
--
-- A single tower routinely hosts several managed-office operators at once:
-- Raheja Towers carries Awfis on 7F, Trend Works on 8F+13F and Quest Office on
-- 3F. Holding the operator on `buildings` forced those three listings to
-- collapse into one row and lose two of the three suites.
--
-- The operator now lives on the space it actually occupies.
-- `buildings.operator_id` is kept for the common single-operator building and
-- is left null when a building has more than one.
-- =============================================================================

alter table spaces
  add column if not exists operator_id    uuid references organisations(id) on delete set null,
  add column if not exists operator_brand text;

create index if not exists spaces_operator on spaces(operator_id);

comment on column spaces.operator_id is
  'The operator running this specific suite. Authoritative for managed and coworking supply.';
comment on column spaces.operator_brand is
  'The operator sub-brand as the source file wrote it, e.g. "BHIVE Platinum".';
comment on column buildings.operator_id is
  'Set only when every option in the building belongs to one operator; null for multi-operator buildings.';
