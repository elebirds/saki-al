-- name: CreateRuntimeLease :one
insert into runtime_lease (name, holder, epoch, lease_until)
values (sqlc.arg(name), sqlc.arg(holder), 1, sqlc.arg(lease_until))
on conflict do nothing
returning name, holder, epoch, lease_until, updated_at;

-- name: RenewRuntimeLease :one
update runtime_lease
set holder = sqlc.arg(holder),
    epoch = epoch + 1,
    lease_until = sqlc.arg(lease_until),
    updated_at = now()
where name = sqlc.arg(name)
  and (holder = sqlc.arg(holder) or lease_until < now())
returning name, holder, epoch, lease_until, updated_at;
