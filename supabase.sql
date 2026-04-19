create table if not exists public.service_state (
  service text primary key,
  generation_count integer not null default 0 check (generation_count >= 0),
  seo_index integer not null default 0 check (seo_index >= 0),
  focus_index integer not null default 0 check (focus_index >= 0),
  tone_index integer not null default 0 check (tone_index >= 0),
  perspective_index integer not null default 0 check (perspective_index >= 0),
  property_location_style_index integer not null default 0 check (property_location_style_index >= 0),
  company_name_counter integer not null default 0 check (company_name_counter >= 0),
  avoid_words_index integer not null default 0 check (avoid_words_index >= 0),
  updated_at timestamptz not null default now()
);

create table if not exists public.review_history (
  id bigserial primary key,
  service text not null,
  area text not null,
  subarea text not null,
  property_type text not null,
  number_of_cameras integer,
  camera_brand text,
  seo_keyword text not null,
  focus_1 text not null,
  focus_2 text not null,
  tone_rule text not null,
  perspective_rule text not null,
  property_location_rule text not null,
  company_name_rule text not null,
  avoid_words_rule text not null,
  similarity double precision,
  review text not null,
  created_at timestamptz not null default now()
);

create index if not exists review_history_service_created_at_idx
  on public.review_history (service, created_at desc);

alter table public.service_state enable row level security;
alter table public.review_history enable row level security;

create or replace function public.reserve_review_state(p_service text)
returns public.service_state
language plpgsql
security definer
set search_path = public
as $$
declare
  current_state public.service_state;
begin
  if p_service is null or btrim(p_service) = '' then
    raise exception 'service is required';
  end if;

  insert into public.service_state (service)
  values (p_service)
  on conflict (service) do nothing;

  select *
  into current_state
  from public.service_state
  where service = p_service
  for update;

  update public.service_state
  set
    generation_count = generation_count + 1,
    seo_index = seo_index + 1,
    focus_index = focus_index + 1,
    tone_index = tone_index + 1,
    perspective_index = perspective_index + 1,
    property_location_style_index = property_location_style_index + 1,
    company_name_counter = company_name_counter + 1,
    avoid_words_index = avoid_words_index + 1,
    updated_at = now()
  where service = p_service;

  return current_state;
end;
$$;

revoke all on function public.reserve_review_state(text) from public;
grant execute on function public.reserve_review_state(text) to service_role;

grant usage on schema public to service_role;
grant select, insert, update on public.service_state to service_role;
grant select, insert on public.review_history to service_role;
grant usage, select on sequence public.review_history_id_seq to service_role;

insert into public.service_state (service)
values
  ('CCTV Installation'),
  ('Wireless Intrusion Alarm System'),
  ('Video Door Phone'),
  ('Intercom System')
on conflict (service) do nothing;
