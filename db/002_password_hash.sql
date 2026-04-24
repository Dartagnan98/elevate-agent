-- add password_hash for email+password login (bcrypt)
alter table users add column if not exists password_hash text;
