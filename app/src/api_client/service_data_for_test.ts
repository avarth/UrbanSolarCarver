// What the local service gives the app when it starts: GET schema (the engine's settings with their defaults, bounds and
// descriptions), GET modes and GET criterion-keys, as service_data_for_test.json holds them. tools/write_app_test_service_data.py
// writes that file from the service's routes, and tests/test_local_web_api_types.py fails while it is out of date, so a test
// that takes its schema or modes from here checks the form against the settings the user gets. A test that needs a setting or a
// mode the service does not have (a made-up field, a bound chosen for an edge) writes its own and says why.
import type { ModeInfo } from "./client";
import serviceData from "./service_data_for_test.json";

/** The reply of GET schema. */
export const SERVICE_SCHEMA: { properties: Record<string, Record<string, unknown>>; [key: string]: unknown } = serviceData.schema;
/** The reply of GET modes, in the service's order. */
export const SERVICE_MODES = serviceData.modes as ModeInfo[];
/** The reply of GET criterion-keys: the settings that belong to a criterion; the others are shared by the criteria. */
export const SERVICE_CRITERION_KEYS: ReadonlySet<string> = new Set(serviceData.criterion_keys);

/** The service's schema with only the settings named (its $defs kept, for threshold's $ref); a name it does not have throws. */
export function serviceSchemaWith(...names: string[]): { properties: Record<string, Record<string, unknown>>; [key: string]: unknown } {
  const missing = names.filter((name) => !(name in SERVICE_SCHEMA.properties));
  if (missing.length > 0) throw new Error(`GET schema has no setting ${missing.join(", ")}`);
  return structuredClone({ ...SERVICE_SCHEMA, properties: Object.fromEntries(names.map((name) => [name, SERVICE_SCHEMA.properties[name]])) });
}

/** The service's modes named, in that order; a name it does not have throws. */
export function serviceModes(...names: string[]): ModeInfo[] {
  return names.map((name) => {
    const mode = SERVICE_MODES.find((candidate) => candidate.name === name);
    if (mode === undefined) throw new Error(`GET modes has no mode ${name}`);
    return structuredClone(mode);
  });
}
