-- Three listing categories: conventional, managed / co-working, and sale.
--
-- Managed and co-working were separate values, but they describe the same
-- listing: the same operator, the same centre, the same seats. Which product a
-- client is buying is decided by the size of their requirement, not by the
-- record:
--
--     fewer than 15 seats  ->  quoted as co-working
--     15 seats or more     ->  quoted as a managed office
--
-- Keeping it on the building made the two categories indistinguishable when
-- editing - the same centre could be filed either way depending on who typed
-- it in - and a co-working filter then hid managed stock that was equally
-- available. The rule now lives in the deck builder, where the requirement is.

-- Fold any co-working record into the managed listing. Nothing is lost: the
-- operator's own product mix is already recorded on `organisations`
-- (offers_managed / offers_coworking), which is where it belongs.
update public.buildings
   set supply_type = 'managed'
 where supply_type = 'coworking';

-- The enum value stays, because dropping a value from a Postgres enum requires
-- rewriting the type and every column that uses it, and nothing now writes it.
-- `services/categories.py` folds it into 'managed' on read, so an old row
-- restored from a backup still reads correctly.
comment on type public.supply_type is
  'Listing category. conventional | managed | sale are the three the desk trades. '
  '''managed'' covers managed and co-working stock, which is one listing - the '
  'product name is decided per requirement by seat count (under 15 = co-working). '
  '''coworking'' is retained only so pre-0005 rows still load; nothing writes it. '
  '''other'' is an out-of-scope catch-all.';

comment on column public.buildings.supply_type is
  'conventional, managed (covers co-working) or sale. See the type comment.';
