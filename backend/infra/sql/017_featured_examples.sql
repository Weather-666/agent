-- Platform-authored questions, independent of Experts and Chat history.
create table if not exists featured_example_categories (
  id text primary key,
  name text not null check (length(trim(name)) between 1 and 60),
  tone text not null check (tone in ('blue', 'green', 'violet', 'orange')),
  sort_order integer not null check (sort_order >= 0),
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table if not exists featured_examples (
  id text primary key,
  category_id text not null references featured_example_categories(id) on delete restrict,
  question text not null check (length(trim(question)) between 1 and 4000),
  status text not null default 'pending' check (status in ('pending', 'live', 'rejected', 'unlisted')),
  sort_order integer not null check (sort_order >= 0),
  review_cycle_days integer check (review_cycle_days in (30, 60, 90)),
  reviewed_at timestamptz,
  reviewed_by text references users(id) on delete set null,
  expires_at timestamptz,
  reject_reason text,
  click_count bigint not null default 0 check (click_count >= 0),
  created_by text references users(id) on delete set null,
  updated_by text references users(id) on delete set null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create index if not exists idx_featured_examples_category_order
  on featured_examples (category_id, sort_order, id);
