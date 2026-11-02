import { lstatSync, realpathSync } from "node:fs"
import { isAbsolute, join, resolve } from "node:path"
import {
  isPlanningLink,
  taskerOption,
  type TaskerCommandInspection,
  type TaskerSandbox,
} from "./command-policy.js"

type Json = Record<string, unknown>
type Stamp<T> = { value: T; generation: number; time: number }
type Lookup = { title: string; type: string; ids: string[] }
type Preview = {
  verb: string
  target: string
  reason: string
  hash: string
  revision: number
}
const TTL = 120_000
const MAX_RECORDS = 1024
const ID = /^(task|epic|memory|doc|link|event|session)_\d+$/
const SAFE_MIGRATIONS: Record<string, string> = {
  missing: "sqlite_file_missing",
  empty: "migration_required",
  legacy_adoptable: "legacy_schema_adoptable",
  pending: "migration_pending",
}
export function sameTaskerSandbox(a: TaskerSandbox, b: TaskerSandbox): boolean {
  return (
    a.scope === b.scope && a.worktree === b.worktree && a.branch === b.branch
  )
}
export function taskerJson(value: unknown): Json | null {
  try {
    if (typeof value === "string") {
      if (value.length > 1_048_576) return null
      value = JSON.parse(value)
    }
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Json)
      : null
  } catch {
    return null
  }
}
function positive(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0
}
function idType(id: string): string {
  return ID.exec(id)?.[1] ?? ""
}
function completeRows(
  data: Json,
  command: TaskerCommandInspection,
): Json[] | null {
  const limit = Number(taskerOption(command, "--limit") ?? 20)
  const maximum =
    command.verb === "list" && command.positionals[0] === "link" ? 1000 : 100
  if (
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > maximum ||
    !Array.isArray(data.items) ||
    data.count !== data.items.length ||
    data.items.length >= limit
  )
    return null
  const rows = data.items.map(taskerJson)
  if (
    rows.some((row) => !row || typeof row.id !== "string" || !ID.test(row.id))
  )
    return null
  const result = rows as Json[]
  return new Set(result.map((row) => row.id)).size === result.length
    ? result
    : null
}
/** Only a worktree-local native doctor can mint one migration capability. */
export function safeTaskerDoctor(data: Json, sandbox: TaskerSandbox): boolean {
  if (
    data.type !== "config_doctor" ||
    data.backend !== "sqlite" ||
    data.status !== "error" ||
    data.parse_ok !== true ||
    data.search_path_ok !== true ||
    data.runtime_ready !== false ||
    data.database_url_present !== false ||
    typeof data.migration_state !== "string" ||
    !Object.hasOwn(SAFE_MIGRATIONS, data.migration_state) ||
    typeof data.migration_code !== "string" ||
    data.migration_code !== SAFE_MIGRATIONS[data.migration_state]
  )
    return false
  if (data.migration_state === "missing" && data.connect_ok !== false)
    return false
  if (
    typeof data.database_path !== "string" ||
    typeof data.config_path !== "string" ||
    !isAbsolute(data.database_path) ||
    !isAbsolute(data.config_path)
  )
    return false
  try {
    const root = realpathSync(sandbox.worktree)
    const directory = join(root, ".codememory")
    if (
      resolve(data.database_path) !== join(directory, "codememory.sqlite3") ||
      ![
        join(directory, "config.yaml"),
        join(directory, "config.sqlite.yaml"),
      ].includes(resolve(data.config_path))
    )
      return false
    for (const path of [
      directory,
      data.config_path,
      ...(data.migration_state === "missing" ? [] : [data.database_path]),
    ]) {
      const state = lstatSync(path)
      if (
        state.isSymbolicLink() ||
        (path === directory ? !state.isDirectory() : !state.isFile()) ||
        state.mode & 0o022 ||
        typeof process.getuid !== "function" ||
        state.uid !== process.getuid()
      )
        return false
    }
    if (data.migration_state === "missing") {
      try {
        lstatSync(data.database_path)
        return false
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") return false
      }
    }
    return true
  } catch {
    return false
  }
}

/** Volatile evidence belongs to one immutable sandbox and mutation generation. */
export class TaskerPlanningEvidence {
  readonly targets = new Map<string, TaskerSandbox>()
  readonly sandbox: TaskerSandbox
  generation = 0
  busy = ""
  request = ""
  researchCount = 0
  researchPending = new Set<string>()
  researchFailed = false
  persisted = false
  private records = new Map<string, Stamp<Json>>()
  private revisions = new Map<string, Stamp<number>>()
  private lookup?: Stamp<Lookup>
  private linkIDs?: Stamp<Array<{ id: string; display: string }>>
  private preview?: Stamp<Preview>
  private doctor?: Stamp<Json>
  constructor(
    sandbox: TaskerSandbox,
    initial?: ReadonlyMap<string, TaskerSandbox>,
    private now = Date.now,
  ) {
    this.sandbox = { ...sandbox }
    for (const [id, target] of initial ?? [])
      if (this.targets.size < MAX_RECORDS && sameTaskerSandbox(target, sandbox))
        this.targets.set(id, this.sandbox)
  }
  private stamp<T>(value: T): Stamp<T> {
    return { value, generation: this.generation, time: this.now() }
  }
  private fresh<T>(stamp?: Stamp<T>): T | undefined {
    return stamp &&
      stamp.generation === this.generation &&
      this.now() - stamp.time >= 0 &&
      this.now() - stamp.time <= TTL
      ? stamp.value
      : undefined
  }
  invalidate(): void {
    this.generation += 1
    this.records.clear()
    this.revisions.clear()
    this.lookup = undefined
    this.linkIDs = undefined
    this.preview = undefined
    this.doctor = undefined
  }
  newRequest(key: string): void {
    if (!key || key === this.request) return
    this.request = key
    this.invalidate()
    // An unfinished child cannot be laundered into a fresh persistence request.
    if (!this.researchPending.size) {
      this.researchCount = 0
      this.researchFailed = false
      this.persisted = false
    }
  }
  private record(id: string): Json | undefined {
    return this.fresh(this.records.get(id))
  }
  private completeLinks(relation: string, target: string): Json[] | null {
    const inventory = this.fresh(this.linkIDs)
    if (!inventory) return null
    // Native list display is the typed edge/target, not arbitrary record prose.
    // Only exact candidates need full inspection; unrelated links cannot match.
    const records = inventory
      .filter((row) => row.display === `${relation} ${target}`)
      .map((row) => this.record(row.id))
    return records.every((record) => record?.type === "link")
      ? (records as Json[])
      : null
  }
  private owns(id: string): boolean {
    const target = this.targets.get(id)
    return Boolean(target && sameTaskerSandbox(target, this.sandbox))
  }
  authorize(command: TaskerCommandInspection): string | null {
    if (this.busy) return "tasker_backend_call_in_flight"
    const [target, field, value] = command.positionals
    if (
      command.kind === "write" &&
      (this.researchPending.size || this.researchFailed)
    )
      return "tasker_research_incomplete"
    if (command.verb === "add") {
      const lookup = this.fresh(this.lookup)
      if (!lookup || lookup.type !== target || lookup.title !== field)
        return "tasker_lookup_required"
      for (const id of lookup.ids) {
        const record = this.record(id)
        if (
          !record ||
          record.type !== target ||
          typeof record.title !== "string"
        )
          return "tasker_candidate_inspection_required"
        if (record.title === field) return "tasker_exact_record_exists"
      }
    }
    if (command.verb === "set") {
      if (
        !this.record(target) ||
        this.fresh(this.revisions.get(target)) !==
          Number(taskerOption(command, "--expected-revision"))
      )
        return "tasker_revision_inspection_required"
    }
    if (command.verb === "link") {
      const links = this.completeLinks(field, value)
      if (!this.record(target) || !this.record(value) || !links)
        return "tasker_link_inspection_required"
      if (
        links.some(
          (link) =>
            link.from_id === target &&
            link.edge_type === field &&
            link.to_id === value,
        )
      )
        return "tasker_duplicate_link"
    }
    if (command.verb === "unlink") {
      const link = this.record(target)
      if (
        !link ||
        typeof link.from_id !== "string" ||
        typeof link.edge_type !== "string" ||
        typeof link.to_id !== "string" ||
        !isPlanningLink(link.from_id, link.edge_type, link.to_id) ||
        !this.record(link.from_id) ||
        !this.record(link.to_id)
      )
        return "tasker_planning_link_inspection_required"
    }
    if (command.verb === "archive" || command.verb === "restore") {
      if (!this.record(target) || !this.owns(target))
        return "tasker_recovery_inspection_required"
      const hash = taskerOption(command, "--apply")
      if (hash) {
        const preview = this.fresh(this.preview)
        if (
          !preview ||
          preview.verb !== command.verb ||
          preview.target !== target ||
          preview.reason !== taskerOption(command, "--reason") ||
          preview.hash !== hash
        )
          return "tasker_recovery_preview_required"
      }
    }
    if (command.verb === "db") {
      const doctor = this.fresh(this.doctor)
      if (!doctor || !safeTaskerDoctor(doctor, this.sandbox))
        return "tasker_safe_doctor_required"
    }
    return null
  }
  reserve(command: TaskerCommandInspection, callID: string): void {
    if (command.kind === "write") {
      this.invalidate()
      if (command.verb !== "db") this.persisted = true
    }
    this.busy = callID
  }
  observe(
    command: TaskerCommandInspection,
    output: unknown,
    exit: unknown,
  ): boolean {
    const data = command.json && exit === 0 ? taskerJson(output) : null
    if (!data) {
      this.invalidate()
      return false
    }
    if (command.verb === "config") {
      this.doctor = safeTaskerDoctor(data, this.sandbox)
        ? this.stamp(data)
        : undefined
      return true
    }
    if (data.error || data.errors || data.stderr) {
      this.invalidate()
      return false
    }
    const [target, title] = command.positionals
    if (command.verb === "find" || command.verb === "list") {
      if (command.verb === "find") this.lookup = undefined
      if (command.verb === "list" && target === "link") this.linkIDs = undefined
      if (
        data.scope_key !== this.sandbox.scope ||
        data.entity_type !==
          (command.verb === "find" ? taskerOption(command, "--type") : target)
      )
        return false
      // Membership in a scoped partial result is authority for that ID, but
      // truncation can never establish absence or a complete edge inventory.
      if (
        Array.isArray(data.items) &&
        data.items.length <= 1000 &&
        data.count === data.items.length
      ) {
        for (const item of data.items) {
          const row = taskerJson(item)
          if (
            row &&
            typeof row.id === "string" &&
            idType(row.id) === data.entity_type
          )
            this.remember(row.id)
        }
      }
      const rows = completeRows(data, command)
      if (!rows) {
        this.lookup = undefined
        this.linkIDs = undefined
        return false
      }
      for (const row of rows)
        if (typeof row.id === "string" && idType(row.id) === data.entity_type)
          this.remember(row.id)
      if (
        command.verb === "find" &&
        data.type === "find_result" &&
        data.query === target &&
        Object.keys(command.options).every((key) =>
          ["--scope", "--type", "--limit"].includes(key),
        )
      ) {
        this.lookup = this.stamp({
          title: target,
          type: String(data.entity_type),
          ids: rows.map((row) => String(row.id)),
        })
      }
      if (
        command.verb === "list" &&
        target === "link" &&
        data.type === "list_result" &&
        Object.keys(command.options).every((key) =>
          ["--scope", "--limit"].includes(key),
        ) &&
        rows.every(
          (row) =>
            typeof row.display === "string" &&
            /^[a-z][a-z-]* (?:task|epic|memory|doc|session)_\d+$/.test(
              row.display,
            ),
        )
      )
        this.linkIDs = this.stamp(
          rows.map((row) => ({
            id: String(row.id),
            display: String(row.display),
          })),
        )
    }
    if (command.verb === "get" && taskerOption(command, "--view") === "full")
      this.records.delete(target)
    if (
      command.verb === "get" &&
      taskerOption(command, "--view") === "full" &&
      data.id === target &&
      data.type === idType(target)
    ) {
      const linkOwned =
        data.type === "link" &&
        typeof data.from_id === "string" &&
        ID.test(data.from_id) &&
        typeof data.to_id === "string" &&
        ID.test(data.to_id) &&
        typeof data.edge_type === "string" &&
        this.fresh(this.linkIDs)?.some(
          (row) =>
            row.id === target &&
            row.display === `${data.edge_type} ${data.to_id}`,
        )
      if (data.scope_key === this.sandbox.scope || linkOwned) {
        this.remember(target)
        if (this.targets.has(target)) {
          const proof = Object.fromEntries(
            [
              "id",
              "type",
              "scope_key",
              "title",
              "status",
              "from_id",
              "edge_type",
              "to_id",
            ]
              .filter(
                (key) =>
                  typeof data[key] === "string" &&
                  (data[key] as string).length <= 4096,
              )
              .map((key) => [key, data[key]]),
          )
          this.records.set(target, this.stamp(proof))
        }
      }
    }
    if (command.verb === "history") this.revisions.delete(target)
    if (
      command.verb === "history" &&
      this.record(target) &&
      data.type === "history" &&
      data.scope_key === this.sandbox.scope &&
      data.query === target &&
      Array.isArray(data.operations) &&
      data.operations.length > 0 &&
      data.operations.length <= 1000 &&
      data.count === data.operations.length
    ) {
      const revisions = data.operations
        .map(taskerJson)
        .filter(
          (op) =>
            op?.target_id === target &&
            op.target_type === idType(target) &&
            op.scope_key === this.sandbox.scope &&
            op.outcome === "applied" &&
            positive(op.resulting_revision),
        )
        .map((op) => Number(op?.resulting_revision))
      if (revisions.length)
        this.revisions.set(target, this.stamp(Math.max(...revisions)))
    }
    if (
      command.verb === "add" &&
      data.type === target &&
      data.scope_key === this.sandbox.scope &&
      data.title === title &&
      typeof data.id === "string" &&
      idType(data.id) === target
    )
      this.remember(data.id)
    if (
      command.verb === "link" &&
      data.type === "link" &&
      typeof data.id === "string" &&
      idType(data.id) === "link" &&
      data.from_id === target &&
      data.edge_type === title &&
      data.to_id === command.positionals[2]
    )
      this.remember(data.id)
    if (
      (command.verb === "archive" || command.verb === "restore") &&
      command.kind === "read"
    ) {
      if (
        data.type === "recovery_plan" &&
        data.command_type === command.verb &&
        data.action === command.verb &&
        data.target_id === target &&
        data.target_type === idType(target) &&
        data.reason === taskerOption(command, "--reason") &&
        positive(data.current_revision) &&
        typeof data.plan_hash === "string" &&
        /^[a-f0-9]{64}$/.test(data.plan_hash) &&
        data.reversible === true
      )
        this.preview = this.stamp({
          verb: command.verb,
          target,
          reason: String(data.reason),
          hash: data.plan_hash,
          revision: data.current_revision,
        })
      else this.preview = undefined
    }
    return true
  }
  private remember(id: string): void {
    if (this.targets.size >= MAX_RECORDS && !this.targets.has(id)) return
    this.targets.set(id, this.sandbox)
  }
}
