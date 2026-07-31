create schema if not exists governance;

create table if not exists governance.datasets (
  dataset_id bigserial primary key,
  dataset_key text not null unique,
  display_name text not null,
  description text,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists governance.catalog_tables (
  table_id bigserial primary key,
  table_key text not null unique,
  table_schema text not null,
  table_name text not null,
  display_name text,
  business_purpose text,
  is_certified boolean not null default false,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
