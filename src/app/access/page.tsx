"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  AlertTriangle,
  KeyRound,
  Lock,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { backend, BackendError } from "@/lib/backend";
import { useAccess, type Permission, type Role } from "@/lib/access";
import { Callout, PageHeader, Section, TableSkeleton, useToast } from "@/components/ui";

type Tab = "people" | "roles";

export default function AccessPage() {
  const [tab, setTab] = useState<Tab>("people");
  const { authReady, me } = useAccess();

  const users = useSWR("access-users", () => backend.users(), { shouldRetryOnError: false });
  const roles = useSWR("access-roles", () => backend.roles(), { shouldRetryOnError: false });
  const permissions = useSWR("access-permissions", () => backend.permissions(), {
    shouldRetryOnError: false,
  });

  if (!authReady) {
    return (
      <>
        <PageHeader eyebrow="Administration" title="User Access" />
        <Callout tone="warning" title="Authentication is not switched on yet">
          <p>
            Run <code>supabase/migrations/0006_auth_and_roles.sql</code> in the Supabase SQL
            editor, then restart the backend. It creates the roles and profiles tables, replaces
            the open <code>anon</code> policies from migration 0004 with permission-scoped ones,
            and seeds the Administrator, Editor and Viewer roles.
          </p>
          <p className="mt-2">
            Until it has run, every screen is open to anyone who can reach the app.
          </p>
        </Callout>
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="User Access"
        description="Create the people who use this tool, and define what each role is allowed to do. Permissions are enforced by the database, not just hidden in the interface."
      />

      <div className="mb-5 flex flex-wrap items-center gap-1 border-b border-border">
        {(
          [
            { value: "people", label: "People", icon: Users, count: users.data?.length },
            { value: "roles", label: "Roles", icon: ShieldCheck, count: roles.data?.length },
          ] as const
        ).map(({ value, label, icon: Icon, count }) => (
          <button
            key={value}
            onClick={() => setTab(value)}
            aria-pressed={tab === value}
            className={`-mb-px flex items-center gap-2 border-b-2 px-3.5 py-2.5 text-sm transition-colors ${
              tab === value
                ? "border-accent font-medium text-accent"
                : "border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
            {count != null ? (
              <span className={`text-xs tabular-nums ${tab === value ? "text-accent/70" : "text-ink-3"}`}>
                {count}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {tab === "people" ? (
        <People
          users={users}
          roles={roles.data ?? []}
          currentUserId={me?.id ?? ""}
          onChange={() => {
            users.mutate();
            roles.mutate();
          }}
        />
      ) : (
        <Roles
          roles={roles}
          permissions={permissions.data ?? []}
          onChange={() => {
            roles.mutate();
            users.mutate();
          }}
        />
      )}
    </>
  );
}

/* ========================================================================= */
/*  People                                                                   */
/* ========================================================================= */

type UsersSWR = ReturnType<typeof useSWR<Awaited<ReturnType<typeof backend.users>>>>;

function People({
  users,
  roles,
  currentUserId,
  onChange,
}: {
  users: UsersSWR;
  roles: Role[];
  currentUserId: string;
  onChange: () => void;
}) {
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  function fail(err: unknown, title: string) {
    toast({
      tone: "danger",
      title,
      message: err instanceof BackendError ? err.message : String(err),
    });
  }

  async function changeRole(id: string, roleKey: string) {
    setBusy(id);
    try {
      await backend.updateUser(id, { role_key: roleKey });
      toast({ tone: "success", message: "Role updated." });
      onChange();
    } catch (err) {
      fail(err, "Could not change the role");
      onChange();
    } finally {
      setBusy(null);
    }
  }

  async function toggleActive(id: string, next: boolean) {
    setBusy(id);
    try {
      await backend.updateUser(id, { is_active: next });
      toast({ tone: "success", message: next ? "Account reactivated." : "Account deactivated." });
      onChange();
    } catch (err) {
      fail(err, "Could not update the account");
    } finally {
      setBusy(null);
    }
  }

  async function resetPassword(id: string, email: string) {
    const password = window.prompt(`New password for ${email} (at least 6 characters)`);
    if (!password) return;
    setBusy(id);
    try {
      await backend.setUserPassword(id, password);
      toast({ tone: "success", message: `Password changed for ${email}.` });
    } catch (err) {
      fail(err, "Could not change the password");
    } finally {
      setBusy(null);
    }
  }

  async function remove(id: string, email: string) {
    if (!window.confirm(`Delete ${email}? They lose access immediately and this cannot be undone.`))
      return;
    setBusy(id);
    try {
      await backend.deleteUser(id);
      toast({ tone: "success", message: `${email} deleted.` });
      onChange();
    } catch (err) {
      fail(err, "Could not delete the account");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-2">
          Everyone with an account. A deactivated person keeps their history but cannot sign in.
        </p>
        <button className="btn-primary" onClick={() => setAdding(true)}>
          <UserPlus className="h-4 w-4" aria-hidden />
          Add person
        </button>
      </div>

      {adding ? (
        <div className="mb-4">
          <NewUserForm
            roles={roles}
            onClose={() => setAdding(false)}
            onCreated={() => {
              setAdding(false);
              onChange();
            }}
          />
        </div>
      ) : null}

      {users.error ? (
        <Callout tone="danger" title="Could not load the people">
          {(users.error as Error).message}
        </Callout>
      ) : users.isLoading ? (
        <TableSkeleton rows={4} />
      ) : (
        <div className="card table-scroll overflow-hidden">
          <table className="w-full min-w-[860px]">
            <thead className="bg-surface-2">
              <tr>
                <th className="th">Person</th>
                <th className="th">Role</th>
                <th className="th">Status</th>
                <th className="th">Last signed in</th>
                <th className="th w-32" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(users.data ?? []).map((user) => {
                const self = user.id === currentUserId;
                return (
                  <tr key={user.id} className={user.is_active ? "" : "opacity-55"}>
                    <td className="td">
                      <span className="block font-medium">
                        {user.full_name || user.email}
                        {self ? <span className="ml-2 text-xs text-ink-3">(you)</span> : null}
                      </span>
                      {user.full_name ? (
                        <span className="block text-xs text-ink-3">{user.email}</span>
                      ) : null}
                    </td>
                    <td className="td">
                      <select
                        className="field h-8 py-0 text-sm"
                        value={user.role_key}
                        disabled={self || busy === user.id}
                        title={self ? "You cannot change your own role" : undefined}
                        onChange={(e) => changeRole(user.id, e.target.value)}
                      >
                        {roles.map((role) => (
                          <option key={role.key} value={role.key}>
                            {role.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="td">
                      <span
                        className={`chip ${
                          user.is_active
                            ? "bg-positive-soft text-positive"
                            : "bg-surface-2 text-ink-3"
                        }`}
                      >
                        {user.is_active ? "Active" : "Deactivated"}
                      </span>
                    </td>
                    <td className="td text-sm text-ink-2">
                      {user.last_sign_in_at
                        ? new Date(user.last_sign_in_at).toLocaleDateString(undefined, {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })
                        : "Never"}
                    </td>
                    <td className="td">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          className="btn-ghost btn-sm"
                          title="Set a new password"
                          disabled={busy === user.id}
                          onClick={() => resetPassword(user.id, user.email)}
                        >
                          <KeyRound className="h-3.5 w-3.5" aria-hidden />
                        </button>
                        {!self ? (
                          <>
                            <button
                              className="btn-ghost btn-sm text-xs"
                              disabled={busy === user.id}
                              onClick={() => toggleActive(user.id, !user.is_active)}
                            >
                              {user.is_active ? "Deactivate" : "Reactivate"}
                            </button>
                            <button
                              className="btn-ghost btn-sm text-danger"
                              title="Delete this account"
                              disabled={busy === user.id}
                              onClick={() => remove(user.id, user.email)}
                            >
                              <Trash2 className="h-3.5 w-3.5" aria-hidden />
                            </button>
                          </>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function NewUserForm({
  roles,
  onClose,
  onCreated,
}: {
  roles: Role[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const toast = useToast();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [roleKey, setRoleKey] = useState(roles.find((r) => !r.is_system)?.key ?? "viewer");
  const [busy, setBusy] = useState(false);

  const role = roles.find((r) => r.key === roleKey);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await backend.createUser({
        email,
        password,
        role_key: roleKey,
        full_name: fullName.trim() || null,
      });
      toast({
        tone: "success",
        title: "Account created",
        message: `${email} can sign in now with the password you set.`,
      });
      onCreated();
    } catch (err) {
      toast({
        tone: "danger",
        title: "Could not create the account",
        message: err instanceof BackendError ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section>
      <form onSubmit={submit}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold tracking-tight">New person</h2>
          <button type="button" className="btn-ghost btn-sm" onClick={onClose}>
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="full-name">
              Full name
            </label>
            <input
              id="full-name"
              className="field"
              placeholder="Priya Nair"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="new-email">
              Email
            </label>
            <input
              id="new-email"
              type="email"
              required
              className="field"
              placeholder="priya@bangaloreoffice.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="new-password">
              Temporary password
            </label>
            <input
              id="new-password"
              type="text"
              required
              minLength={6}
              className="field"
              placeholder="At least 6 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="mt-1 text-xs text-ink-3">
              Share this with them directly. They can be given a new one at any time.
            </p>
          </div>
          <div>
            <label className="label" htmlFor="new-role">
              Role
            </label>
            <select
              id="new-role"
              className="field"
              value={roleKey}
              onChange={(e) => setRoleKey(e.target.value)}
            >
              {roles.map((r) => (
                <option key={r.key} value={r.key}>
                  {r.name}
                </option>
              ))}
            </select>
            {role?.description ? (
              <p className="mt-1 text-xs text-ink-3">{role.description}</p>
            ) : null}
          </div>
        </div>

        <div className="mt-5 flex gap-2">
          <button className="btn-primary" disabled={busy}>
            <UserPlus className="h-4 w-4" aria-hidden />
            {busy ? "Creating…" : "Create account"}
          </button>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Section>
  );
}

/* ========================================================================= */
/*  Roles                                                                    */
/* ========================================================================= */

type RolesSWR = ReturnType<typeof useSWR<Role[]>>;

function Roles({
  roles,
  permissions,
  onChange,
}: {
  roles: RolesSWR;
  permissions: Permission[];
  onChange: () => void;
}) {
  const [creating, setCreating] = useState(false);

  const grouped = useMemo(() => {
    const map = new Map<string, Permission[]>();
    for (const permission of permissions) {
      const list = map.get(permission.category) ?? [];
      list.push(permission);
      map.set(permission.category, list);
    }
    return [...map.entries()];
  }, [permissions]);

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-2">
          A role is a set of permissions. Tick what it may do, then assign people to it on the
          People tab.
        </p>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" aria-hidden />
          New role
        </button>
      </div>

      {creating ? (
        <div className="mb-4">
          <RoleEditor
            grouped={grouped}
            onClose={() => setCreating(false)}
            onSaved={() => {
              setCreating(false);
              onChange();
            }}
          />
        </div>
      ) : null}

      {roles.error ? (
        <Callout tone="danger" title="Could not load the roles">
          {(roles.error as Error).message}
        </Callout>
      ) : roles.isLoading ? (
        <TableSkeleton rows={3} />
      ) : (
        <div className="space-y-4">
          {(roles.data ?? []).map((role) => (
            <RoleEditor key={role.key} role={role} grouped={grouped} onSaved={onChange} />
          ))}
        </div>
      )}
    </>
  );
}

function RoleEditor({
  role,
  grouped,
  onClose,
  onSaved,
}: {
  role?: Role;
  grouped: [string, Permission[]][];
  onClose?: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [chosen, setChosen] = useState<Set<string>>(new Set(role?.permissions ?? []));
  const [busy, setBusy] = useState(false);

  const isNew = !role;
  const system = role?.is_system ? role : null;   // narrows for the locked branch
  const locked = Boolean(system);
  const wildcard = chosen.has("*");

  const dirty =
    isNew ||
    name !== role.name ||
    (description ?? "") !== (role.description ?? "") ||
    chosen.size !== role.permissions.length ||
    [...chosen].some((p) => !role.permissions.includes(p));

  function toggle(key: string) {
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function fail(err: unknown, title: string) {
    toast({
      tone: "danger",
      title,
      message: err instanceof BackendError ? err.message : String(err),
    });
  }

  async function save() {
    setBusy(true);
    try {
      if (isNew) {
        await backend.createRole({ name, permissions: [...chosen], description });
        toast({ tone: "success", message: `Role ${name} created.` });
      } else {
        await backend.updateRole(role.key, {
          name,
          description,
          permissions: [...chosen],
        });
        toast({ tone: "success", message: `Role ${name} saved.` });
      }
      onSaved();
    } catch (err) {
      fail(err, isNew ? "Could not create the role" : "Could not save the role");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!role) return;
    if (!window.confirm(`Delete the ${role.name} role?`)) return;
    setBusy(true);
    try {
      await backend.deleteRole(role.key);
      toast({ tone: "success", message: `Role ${role.name} deleted.` });
      onSaved();
    } catch (err) {
      fail(err, "Could not delete the role");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {system ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{system.name}</span>
              <span className="chip bg-accent-soft text-accent">
                <Lock className="h-3 w-3" aria-hidden />
                built-in
              </span>
              <span className="chip bg-surface-2 text-ink-2">
                {system.user_count} {system.user_count === 1 ? "person" : "people"}
              </span>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label">Role name</label>
                <input
                  className="field"
                  placeholder="Research analyst"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div>
                <label className="label">What it is for</label>
                <input
                  className="field"
                  placeholder="Reads supply and builds proposals, cannot delete"
                  value={description ?? ""}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
            </div>
          )}
          {system ? <p className="mt-1.5 text-sm text-ink-2">{system.description}</p> : null}
        </div>

        {!locked ? (
          <div className="flex items-center gap-2">
            <button className="btn-primary" disabled={busy || !dirty || !name.trim()} onClick={save}>
              <Save className="h-4 w-4" aria-hidden />
              {busy ? "Saving…" : isNew ? "Create role" : "Save"}
            </button>
            {isNew ? (
              <button className="btn-ghost" onClick={onClose}>
                Cancel
              </button>
            ) : (
              <button
                className="btn-ghost text-danger"
                disabled={busy}
                onClick={remove}
                title={
                  role.user_count > 0
                    ? "Move the people holding this role elsewhere first"
                    : "Delete this role"
                }
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            )}
          </div>
        ) : null}
      </div>

      {wildcard ? (
        <Callout tone="info">
          This role holds every permission, including any added by future features. It cannot be
          edited or deleted, so there is always a way back into user management.
        </Callout>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {grouped.map(([category, items]) => (
            <div key={category}>
              <p className="mb-2 text-xs font-semibold tracking-wide text-ink-3 uppercase">
                {category}
              </p>
              <ul className="space-y-2">
                {items.map((permission) => (
                  <li key={permission.key}>
                    <label className="flex cursor-pointer items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        disabled={locked}
                        checked={chosen.has(permission.key)}
                        onChange={() => toggle(permission.key)}
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">{permission.label}</span>
                        <span className="block text-xs text-ink-3">{permission.description}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {!locked && !wildcard && chosen.has("users.manage") ? (
        <p className="mt-4 flex items-start gap-2 text-xs text-warning">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Anyone with this role can create accounts and change what every other role may do.
        </p>
      ) : null}

      {!locked && !isNew && role.user_count > 0 ? (
        <p className="mt-3 text-xs text-ink-3">
          {role.user_count} {role.user_count === 1 ? "person holds" : "people hold"} this role.
          Saving changes what they can do immediately.
        </p>
      ) : null}
    </Section>
  );
}
