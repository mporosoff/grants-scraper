import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, rm, writeFile } from "node:fs/promises";

// A crashed build leaves an explicit lock for inspection, never an automatic
// takeover of a possibly active writer. Publication still requires package gates.
export async function withBuildLock(directory, operation) {
  await mkdir(directory, {recursive: true});
  const lock = new URL("semantic-build.lock", directory);
  const handle = await open(lock, "wx");
  try {
    await handle.writeFile(JSON.stringify({pid: process.pid, started_at: new Date().toISOString()}));
    return await operation();
  } finally {
    await handle.close();
    await rm(lock);
  }
}

// Stage all outputs before replacement. Callers put the manifest last. Roll back
// a failed replacement; a process crash is caught by integrity gates and retains
// the committed/deployed release. No incomplete generation can pass publication.
export async function writeCoherentFiles(entries, replace = rename) {
  const staged = [];
  try {
    for (const [path, bytes] of entries) {
      const previous = await readFile(path).catch(error => {
        if (error.code === "ENOENT") return null;
        throw error;
      });
      const temporary = new URL(`${path.pathname.split("/").at(-1)}.${randomUUID()}.tmp`, path);
      staged.push({path, previous, temporary, changed: false});
      await writeFile(temporary, bytes, {flag: "wx"});
    }
    for (const row of staged) {
      await replace(row.temporary, row.path);
      row.changed = true;
    }
  } catch (error) {
    for (const row of staged.filter(item => item.changed).reverse()) {
      if (row.previous === null) await rm(row.path);
      else {
        await writeFile(row.temporary, row.previous);
        await rename(row.temporary, row.path);
      }
    }
    throw error;
  } finally {
    for (const row of staged) await rm(row.temporary, {force: true});
  }
}
