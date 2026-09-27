import { api } from "./api";
import { Field, Form, num, text } from "./components";
import type { Asset, Part } from "./types";

const types = (
  <>
    <option value="motor">Motor</option>
    <option value="pump">Pump</option>
    <option value="fan">Fan</option>
    <option value="drive">Drive</option>
  </>
);
export function AssetForm({ done }: { done: () => Promise<void> }) {
  return (
    <Form
      label="Create asset"
      onSubmit={async (d) => {
        await api("/assets", {
          id: text(d, "id"),
          name: text(d, "name"),
          area: text(d, "area"),
          equipment_class: text(d, "equipment_class"),
          rated_power: num(d, "rated_power"),
          duty_cycle: num(d, "duty_cycle"),
          safety: num(d, "safety"),
          production_impact: num(d, "production_impact"),
          hourly_cost: num(d, "hourly_cost"),
          vibration_limit: num(d, "vibration_limit"),
          temperature_limit: num(d, "temperature_limit"),
        });
        await done();
      }}
    >
      <div className="form-grid">
        <Field label="Asset ID">
          <input
            name="id"
            required
            pattern="[a-zA-Z0-9_-]+"
            placeholder="MTR-042"
            maxLength={40}
          />
        </Field>
        <Field label="Name">
          <input name="name" required maxLength={100} />
        </Field>
        <Field label="Production area">
          <input name="area" required maxLength={80} />
        </Field>
        <Field label="Equipment class">
          <select name="equipment_class">{types}</select>
        </Field>
        <Field label="Rated power (kW)">
          <input
            name="rated_power"
            type="number"
            min="0.1"
            step="any"
            required
          />
        </Field>
        <Field label="Duty cycle (0-1)">
          <input
            name="duty_cycle"
            type="number"
            min="0"
            max="1"
            step="0.01"
            required
          />
        </Field>
        <Field label="Safety consequence (1-10)">
          <input name="safety" type="number" min="1" max="10" required />
        </Field>
        <Field label="Production impact (1-10)">
          <input
            name="production_impact"
            type="number"
            min="1"
            max="10"
            required
          />
        </Field>
        <Field label="Downtime exposure (USD/hour)">
          <input name="hourly_cost" type="number" min="0" step="any" required />
        </Field>
        <Field label="Vibration threshold (mm/s)">
          <input
            name="vibration_limit"
            type="number"
            min="0.01"
            step="any"
            required
          />
        </Field>
        <Field label="Temperature threshold (°C)">
          <input
            name="temperature_limit"
            type="number"
            min="0.1"
            step="any"
            required
          />
        </Field>
      </div>
    </Form>
  );
}
export function TelemetryForm({
  asset,
  done,
}: {
  asset: Asset;
  done: () => Promise<void>;
}) {
  return (
    <Form
      label="Ingest readings"
      onSubmit={async (d) => {
        const rows = text(d, "csv")
          .trim()
          .split(/\r?\n/)
          .filter(Boolean)
          .map((line, index) => {
            const columns = line.split(",").map((v) => v.trim());
            if (
              columns.length !== 4 ||
              columns
                .slice(1)
                .some((v) => v === "" || !Number.isFinite(Number(v)))
            )
              throw new Error(
                `Line ${index + 1}: expected timestamp,vibration,temperature,load`,
              );
            const [observed_at, vibration, temperature, load] = columns;
            return {
              observed_at,
              vibration: Number(vibration),
              temperature: Number(temperature),
              load: Number(load),
              source: text(d, "source"),
            };
          });
        await api(`/assets/${asset.id}/telemetry`, {
          readings: rows,
          analyze: d.get("analyze") === "on",
        });
        await done();
      }}
    >
      <p className="muted">
        Add one reading per line: ISO timestamp with timezone, vibration (mm/s),
        temperature (°C), load (%). Duplicate timestamps from the same source
        are ignored.
      </p>
      <Field label="Source / gateway identifier">
        <input
          name="source"
          required
          maxLength={80}
          placeholder="line3-gateway"
        />
      </Field>
      <Field label="Readings (CSV, without header)">
        <textarea
          name="csv"
          rows={8}
          required
          placeholder="2026-09-27T12:00:00Z,4.2,71,80"
        />
      </Field>
      <label className="check">
        <input name="analyze" type="checkbox" />
        Queue agent analysis after ingestion
      </label>
    </Form>
  );
}
export function PartForm({
  part,
  done,
}: {
  part?: Part;
  done: () => Promise<void>;
}) {
  return (
    <Form
      label="Save inventory"
      onSubmit={async (d) => {
        const id = text(d, "id");
        await api(
          `/parts/${id}`,
          { id, name: text(d, "name"), stock: num(d, "stock") },
          "PUT",
        );
        await done();
      }}
    >
      <Field label="Part ID">
        <input
          name="id"
          required
          defaultValue={part?.id}
          readOnly={!!part}
          pattern="[a-zA-Z0-9_-]+"
        />
      </Field>
      <Field label="Part name">
        <input name="name" required defaultValue={part?.name} />
      </Field>
      <Field
        label={`Physical stock${part ? ` (${part.reserved} reserved)` : ""}`}
      >
        <input
          name="stock"
          type="number"
          min={part?.reserved ?? 0}
          required
          defaultValue={part?.stock}
        />
      </Field>
    </Form>
  );
}
export function WindowForm({ done }: { done: () => Promise<void> }) {
  return (
    <Form
      label="Add maintenance window"
      onSubmit={async (d) => {
        await api("/windows", {
          area: text(d, "area"),
          starts_at: new Date(text(d, "starts_at")).toISOString(),
          ends_at: new Date(text(d, "ends_at")).toISOString(),
          production_fraction: num(d, "production_fraction"),
          technicians: num(d, "technicians"),
          permit_ready: d.get("permit_ready") === "on",
        });
        await done();
      }}
    >
      <Field label="Production area (must match asset)">
        <input name="area" required />
      </Field>
      <div className="form-grid">
        <Field label="Start (your local time)">
          <input name="starts_at" type="datetime-local" required />
        </Field>
        <Field label="End (your local time)">
          <input name="ends_at" type="datetime-local" required />
        </Field>
        <Field label="Production utilization (0-1)">
          <input
            name="production_fraction"
            type="number"
            min="0"
            max="1"
            step="0.01"
            required
          />
        </Field>
        <Field label="Available technicians">
          <input name="technicians" type="number" min="0" required />
        </Field>
      </div>
      <label className="check">
        <input name="permit_ready" type="checkbox" />
        Permit is ready
      </label>
    </Form>
  );
}
export function ProcedureForm({ done }: { done: () => Promise<void> }) {
  return (
    <Form
      label="Save procedure"
      onSubmit={async (d) => {
        const id = text(d, "id");
        const raw = text(d, "parts").trim();
        const parts = raw
          ? raw
              .split("\n")
              .filter(Boolean)
              .map((line) => {
                const [part_id, quantity] = line.split(",");
                return { part_id: part_id.trim(), quantity: Number(quantity) };
              })
          : [];
        await api(
          `/procedures/${id}`,
          {
            id,
            equipment_class: text(d, "equipment_class"),
            title: text(d, "title"),
            duration_hours: num(d, "duration_hours"),
            source: text(d, "source"),
            parts,
            steps: text(d, "steps")
              .split("\n")
              .map((s) => s.trim())
              .filter(Boolean),
          },
          "PUT",
        );
        await done();
      }}
    >
      <div className="form-grid">
        <Field label="Procedure ID">
          <input name="id" required pattern="[a-zA-Z0-9_-]+" />
        </Field>
        <Field label="Equipment class">
          <select name="equipment_class">{types}</select>
        </Field>
      </div>
      <Field label="Title">
        <input name="title" required />
      </Field>
      <div className="form-grid">
        <Field label="Expected duration (hours)">
          <input
            name="duration_hours"
            type="number"
            min="0.1"
            step="any"
            required
          />
        </Field>
        <Field label="Approved SOP reference / version">
          <input
            name="source"
            required
            placeholder="Site SOP identifier and revision"
          />
        </Field>
      </div>
      <Field label="Required parts (part ID,quantity per line)">
        <textarea name="parts" rows={3} />
      </Field>
      <Field label="Approved procedure steps (one per line)">
        <textarea name="steps" rows={6} required />
      </Field>
    </Form>
  );
}
export function UserForm({ done }: { done: () => Promise<void> }) {
  return (
    <Form
      label="Create user"
      onSubmit={async (d) => {
        await api("/users", {
          username: text(d, "username"),
          password: text(d, "password"),
          role: text(d, "role"),
        });
        await done();
      }}
    >
      <Field label="Username">
        <input name="username" autoComplete="off" minLength={3} required />
      </Field>
      <Field label="Initial password (12+ characters)">
        <input
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          required
        />
      </Field>
      <Field label="Role">
        <select name="role">
          <option value="supervisor">
            Supervisor - approves work and procedures
          </option>
          <option value="planner">Planner - manages inputs and analysis</option>
          <option value="technician">
            Technician - completes approved work
          </option>
        </select>
      </Field>
    </Form>
  );
}
