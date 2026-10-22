import { readdir, mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)), '..')
const schemaDir = resolve(root, 'docs/schemas')
const outputDir = resolve(root, 'frontend/src/generated')
const schemas = (await readdir(schemaDir)).filter((file) => file.endsWith('.schema.json'))

await mkdir(outputDir, { recursive: true })

// Adapt draft-2020 tuples to the equivalent tuple syntax understood by the
// TS compiler. The exported schema documents retain their original dialect.
function compilerSchema(value) {
  if (Array.isArray(value)) return value.map(compilerSchema)
  if (!value || typeof value !== 'object') return value
  const result = Object.fromEntries(Object.entries(value).map(([key, child]) => [key, compilerSchema(child)]))
  if (Array.isArray(result.prefixItems)) {
    result.items = result.prefixItems
    result.additionalItems = false
    delete result.prefixItems
  }
  return result
}

for (const file of schemas) {
  const name = file.replace('.schema.json', '')
  const schema = compilerSchema(JSON.parse(await readFile(resolve(schemaDir, file), 'utf8')))
  const types = await compile(schema, name, {
    bannerComment: '',
    style: { singleQuote: true, semi: false },
  })
  await writeFile(resolve(outputDir, `${name}.ts`), types)
}
